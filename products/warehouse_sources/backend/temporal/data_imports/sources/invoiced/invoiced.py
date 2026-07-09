import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.settings import INVOICED_ENDPOINTS

INVOICED_BASE_URL = "https://api.invoiced.com"
INVOICED_HOST = "api.invoiced.com"
# List endpoints paginate GitHub-style (page/per_page + Link header) in pages of up to 100.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Cheap list endpoint used to confirm an API key is genuine. Invoiced API keys are
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/customers"


class InvoicedRetryableError(Exception):
    pass


class InvoicedUntrustedURLError(Exception):
    """A pagination URL (resumed or upstream) pointed somewhere other than the Invoiced API."""


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Invoiced API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `Link` header URLs are followed
    verbatim with the customer's API key installed as HTTP Basic auth. Validating the scheme and host
    keeps a poisoned resume state or a hostile upstream response from retargeting the request at
    another host and leaking the key (SSRF). Returns the URL unchanged when it is trusted.
    """
    parts = urlsplit(url)
    if not (parts.scheme == "https" and parts.netloc == INVOICED_HOST):
        raise InvoicedUntrustedURLError(f"Refusing to follow pagination URL outside {INVOICED_BASE_URL}")
    return url


@dataclasses.dataclass
class InvoicedResumeConfig:
    # Full URL of the next page, taken verbatim from the Link header's rel="next". It carries
    # the original request's per_page/sort/updated_after params, so a crashed sync resumes from
    # the page after the last one yielded; merge dedupes the re-pulled page on `id`.
    next_url: str | None = None


def _get_session(api_key: str) -> requests.Session:
    # Invoiced authenticates via HTTP Basic with the API key as the username and a blank password.
    # `allow_redirects=False` stops a redirect response from sending the API key to another host, and
    # `retry=Retry(total=0)` disables the adapter's built-in retries — `_fetch_page` already retries
    # 429/5xx via tenacity, so the adapter default would stack a second retry layer.
    session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
        retry=Retry(total=0),
    )
    session.auth = (api_key, "")
    return session


def _to_unix_timestamp(value: Any) -> int:
    """Convert an incremental cursor to the UNIX epoch integer `updated_after` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    return int(value)


def _build_initial_url(
    path: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    # An explicit ascending updated_at sort keeps page traversal deterministic and lets the
    # pipeline checkpoint the incremental watermark per batch (sort_mode="asc"). `sort` is
    # documented on every list endpoint we sync ("Column to sort by, i.e. name asc").
    params: dict[str, Any] = {"per_page": PAGE_SIZE, "sort": "updated_at asc"}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["updated_after"] = _to_unix_timestamp(db_incremental_field_last_value)
    return f"{INVOICED_BASE_URL}{path}?{urlencode(params, quote_via=quote)}"


@retry(
    retry=retry_if_exception_type((InvoicedRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # `url` is already absolute — either the initial endpoint URL or a verbatim Link rel="next",
    # so we never re-send query params (they're baked into the pagination URL).
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Invoiced enforces rate limits via 429 with no published numeric limits; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise InvoicedRetryableError(f"Invoiced API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Invoiced API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # List endpoints return a top-level JSON array; pagination lives in the Link header.
    if not isinstance(data, list):
        raise InvoicedRetryableError(f"Invoiced returned an unexpected payload for {url}: {type(data).__name__}")

    next_url = response.links.get("next", {}).get("url")
    return data, next_url


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InvoicedResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INVOICED_ENDPOINTS[endpoint]
    session = _get_session(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.next_url:
        # Resume state comes from Redis — validate before sending the API key to it.
        url: Optional[str] = _validate_pagination_url(resume.next_url)
        logger.debug(f"Invoiced: resuming {endpoint} from {url}")
    else:
        url = _build_initial_url(config.path, should_use_incremental_field, db_incremental_field_last_value)

    while url:
        items, next_url = _fetch_page(session, url, logger)
        if items:
            yield items

        # No Link rel="next" means we've reached the last page.
        if not next_url:
            break

        # The upstream-supplied next-page URL is followed verbatim with the API key — pin it to the
        # Invoiced API so a hostile response can't retarget the authenticated request.
        url = _validate_pagination_url(next_url)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(InvoicedResumeConfig(next_url=url))


def invoiced_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InvoicedResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INVOICED_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        # Rows are requested with an explicit `sort=updated_at asc` (see _build_initial_url).
        sort_mode="asc",
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = _get_session(api_key)
    try:
        response = session.get(f"{INVOICED_BASE_URL}{path}", params={"per_page": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Invoiced: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Invoiced returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Invoiced API key"
    return False, message or "Could not validate Invoiced API key"
