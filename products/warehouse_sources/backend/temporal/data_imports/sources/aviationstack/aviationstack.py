import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1"
DEFAULT_PAGE_SIZE = 100

# aviationstack returns HTTP 200 with an error envelope (`{"error": {"code": ...}}`). Transient
# body-level codes are retried with backoff; every other code (bad/blocked key, plan gating,
# exhausted monthly quota — e.g. invalid_access_key, missing_access_key, inactive_user,
# function_access_restricted, https_access_restricted, usage_limit_reached) fails fast and is
# surfaced as a permanent failure matched by AviationstackSource.get_non_retryable_errors.
_RETRYABLE_ERROR_CODES = {"rate_limit_reached"}


class AviationstackRetryableError(Exception):
    pass


class AviationstackAPIError(Exception):
    pass


@dataclasses.dataclass
class AviationstackResumeConfig:
    # Offset of the next page to fetch — aviationstack uses limit/offset pagination.
    next_offset: int


@retry(
    retry=retry_if_exception_type((AviationstackRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # `url` carries no secrets — the access_key lives in `params`, which requests keeps out of the
    # log line emitted here — so it's safe to log on error.
    response = session.get(url, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise AviationstackRetryableError(
            f"aviationstack API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"aviationstack API error: status={response.status_code}, url={url}")
        # Don't use `response.raise_for_status()` — it embeds `response.url` (which carries the
        # access_key query param) in the error message, and that exception is later logged via
        # `str(error)` outside the tracked session's redaction. Strip the query string instead.
        kind = "Client Error" if response.status_code < 500 else "Server Error"
        safe_url = response.url.split("?", 1)[0]
        raise requests.HTTPError(
            f"{response.status_code} {kind}: {response.reason} for url: {safe_url}", response=response
        )

    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    if error:
        code = error.get("code", "unknown")
        message = error.get("message", "")
        if code in _RETRYABLE_ERROR_CODES:
            raise AviationstackRetryableError(f"aviationstack API error (retryable) [{code}]: {message}")
        # Permanent codes (and anything unrecognized) fail fast — the keys in
        # get_non_retryable_errors match on the `[code]` token.
        raise AviationstackAPIError(f"aviationstack API error [{code}]: {message}")

    return body


def get_rows(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AviationstackResumeConfig],
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[Any]:
    config = AVIATIONSTACK_ENDPOINTS[endpoint]
    url = f"{AVIATIONSTACK_BASE_URL}{config.path}"
    # `access_key` is passed as a query param on every request, so mask its value from the
    # tracked session's logged URLs and captured samples.
    session = make_tracked_session(redact_values=(access_key,))
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.next_offset if resume is not None else 0
    if resume is not None:
        logger.debug(f"aviationstack: resuming {endpoint} from offset={offset}")

    while True:
        params = {"access_key": access_key, "offset": offset, "limit": page_size}
        body = _fetch_page(session, url, params, logger)

        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list):
            items = []

        pagination = body.get("pagination") if isinstance(body, dict) else None
        total = pagination.get("total") if isinstance(pagination, dict) else None

        next_offset = offset + page_size
        has_more = len(items) >= page_size and (not isinstance(total, int) or next_offset < total)

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
                # page rather than skipping it — merge/replace dedupes the re-pulled rows.
                if has_more:
                    resumable_source_manager.save_state(AviationstackResumeConfig(next_offset=next_offset))

        if not has_more or len(items) == 0:
            break
        offset = next_offset

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def aviationstack_source(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AviationstackResumeConfig],
) -> SourceResponse:
    config = AVIATIONSTACK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_key=access_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
    )


def validate_credentials(access_key: str) -> bool:
    # `/countries` is a static reference endpoint available on every plan (including free), so it's a
    # cheap probe that the access key is genuine without depending on a paid-tier endpoint.
    url = f"{AVIATIONSTACK_BASE_URL}/countries"
    params: dict[str, Any] = {"access_key": access_key, "limit": 1}
    try:
        session = make_tracked_session(redact_values=(access_key,))
        response = session.get(url, params=params, timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and bool(body.get("error")))
