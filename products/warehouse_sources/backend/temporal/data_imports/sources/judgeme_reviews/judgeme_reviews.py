import time
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import (
    JUDGEME_REVIEWS_ENDPOINTS,
)

# The base URL already includes the `/v1` API version segment; endpoint paths are appended to it.
JUDGEME_BASE_URL = "https://judge.me/api/v1"
# per_page maxes out at 100 per Judge.me's docs.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Judge.me doesn't publish precise rate limits but does send Retry-After on 429; cap how long a
# single wait can be so a bogus header can't stall the worker.
MAX_RETRY_AFTER_SECONDS = 60
# Cheap endpoint used to confirm the token + shop domain pair is genuine. The private token is
# shop-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/reviews/count"


class JudgeMeReviewsRetryableError(Exception):
    pass


@dataclasses.dataclass
class JudgeMeReviewsResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _normalize_shop_domain(shop_domain: str) -> str:
    # Users paste the domain straight from their browser; strip any scheme/trailing slash so the
    # value matches the bare `example.myshopify.com` format the API expects.
    domain = shop_domain.strip()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]
    return domain.rstrip("/")


def _make_session(api_token: str) -> requests.Session:
    # The private token goes in the X-Api-Token header (per the OpenAPI spec) so it never appears
    # in request URLs; `redact_values` masks it in logged headers and captured samples too.
    return make_tracked_session(
        headers={"X-Api-Token": api_token, "Accept": "application/json"},
        redact_values=(api_token,),
    )


@retry(
    retry=retry_if_exception_type((JudgeMeReviewsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    shop_domain: str,
    page: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{JUDGEME_BASE_URL}{path}",
        params={"shop_domain": shop_domain, "page": page, "per_page": PAGE_SIZE},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            time.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
        raise JudgeMeReviewsRetryableError(f"Judge.me API rate limited: status=429, path={path}")

    if response.status_code >= 500:
        raise JudgeMeReviewsRetryableError(
            f"Judge.me API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"Judge.me API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Every list endpoint returns an object envelope (`{"<resource>": [...], ...}`); a bare array
    # or other type means a malformed response.
    if not isinstance(data, dict):
        raise JudgeMeReviewsRetryableError(f"Judge.me returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(value)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def get_rows(
    api_token: str,
    shop_domain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JudgeMeReviewsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = JUDGEME_REVIEWS_ENDPOINTS[endpoint]
    session = _make_session(api_token)
    domain = _normalize_shop_domain(shop_domain)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"Judge.me: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, config.path, domain, page, logger)

        # The resource key is always present in a well-formed envelope; missing it means a malformed
        # response, so fail loudly rather than silently advancing the cursor past lost rows.
        items = data.get(config.list_key)
        if not isinstance(items, list):
            raise JudgeMeReviewsRetryableError(
                f"Judge.me response for {endpoint} is missing the '{config.list_key}' list"
            )
        if items:
            yield items

        # There is no `has_more` flag in the envelope, and the API may cap per_page below what we
        # request, so an empty page is the only reliable end-of-collection signal.
        if not items:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(JudgeMeReviewsResumeConfig(next_page=page))


def judgeme_reviews_source(
    api_token: str,
    shop_domain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JudgeMeReviewsResumeConfig],
) -> SourceResponse:
    config = JUDGEME_REVIEWS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            shop_domain=shop_domain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_token: str, shop_domain: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single cheap endpoint to validate the token + shop domain pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = _make_session(api_token)
    domain = _normalize_shop_domain(shop_domain)
    try:
        response = session.get(
            f"{JUDGEME_BASE_URL}{path}",
            params={"shop_domain": domain},
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Judge.me: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Judge.me returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str, shop_domain: str) -> tuple[bool, str | None]:
    status, message = check_access(api_token, shop_domain)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Judge.me shop domain or API token"
    return False, message or "Could not validate Judge.me credentials"
