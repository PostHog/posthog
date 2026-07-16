import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import E2B_ENDPOINTS

# E2B exposes a single global base URL; there are no regional hosts.
E2B_BASE_URL = "https://api.e2b.app"

# Cursor pagination: `limit` maxes out at 100, and the next cursor is returned in this response header.
E2B_PAGE_LIMIT = 100
NEXT_TOKEN_HEADER = "X-Next-Token"


class E2BRetryableError(Exception):
    pass


@dataclasses.dataclass
class E2BResumeConfig:
    # Opaque cursor to fetch the next page from (E2B's `nextToken`). `None` starts at the first page.
    # A job only ever syncs one endpoint, so a single token slot is unambiguous.
    next_token: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # Cheapest authenticated probe: list a single sandbox. 200 means the team-scoped key is genuine,
    # 401/403 means it isn't. Anything else — a timeout, connection error, rate limit, or 5xx — is a
    # transient upstream problem that says nothing about the key, so raise rather than mislabel a valid
    # key "invalid" and send the user down the wrong recovery path.
    # `redact_values` masks the key from tracked HTTP samples (the `X-API-Key` header isn't on the
    # generic scrubber's denylist); `allow_redirects=False` keeps the key from replaying to another host.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    response = session.get(
        f"{E2B_BASE_URL}/v2/sandboxes",
        headers=_get_headers(api_key),
        params={"limit": 1},
        timeout=10,
    )
    if response.status_code == 200:
        return True
    if response.status_code in (401, 403):
        return False
    raise E2BRetryableError(f"E2B credential probe failed (retryable): status={response.status_code}")


@retry(
    retry=retry_if_exception_type(
        (
            E2BRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> requests.Response:
    response = session.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise E2BRetryableError(f"E2B API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"E2B API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[E2BResumeConfig],
) -> Iterator[Any]:
    config = E2B_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values` masks
    # the key from tracked HTTP samples; `allow_redirects=False` keeps it from replaying to another host.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    url = f"{E2B_BASE_URL}{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_token = resume.next_token if resume else None
    if next_token:
        logger.debug(f"E2B: resuming {endpoint} from cursor")

    while True:
        params: dict[str, Any] = {"limit": E2B_PAGE_LIMIT}
        if next_token:
            params["nextToken"] = next_token

        response = _fetch_page(session, url, headers, params, logger)
        items = response.json()
        # E2B list endpoints return a bare JSON array, not a wrapped `{data: [...]}` envelope.
        if not isinstance(items, list):
            logger.warning(f"E2B: unexpected non-list response for {endpoint}, stopping")
            break

        page_token = response.headers.get(NEXT_TOKEN_HEADER) or None

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it;
                # merge dedupes on the primary key. Only persist while there's another page to fetch.
                if page_token:
                    resumable_source_manager.save_state(E2BResumeConfig(next_token=page_token))

        # Terminate when the API stops handing back a cursor, or hands back the same one (defensive
        # guard against an endpoint that echoes the token instead of dropping it).
        if not page_token or page_token == next_token:
            break
        next_token = page_token

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def e2b_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[E2BResumeConfig],
) -> SourceResponse:
    config = E2B_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
