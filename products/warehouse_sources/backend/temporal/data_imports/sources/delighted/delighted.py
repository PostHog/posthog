import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.settings import (
    DELIGHTED_ENDPOINTS,
    DelightedEndpointConfig,
)

DELIGHTED_HOST = "api.delighted.com"
DELIGHTED_BASE_URL = f"https://{DELIGHTED_HOST}/v1"
# Delighted caps list pages at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Upper bound on how long we honor a server-provided Retry-After header.
MAX_RETRY_AFTER_SECONDS = 120


class DelightedRetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class DelightedUnexpectedRedirectError(Exception):
    """Raised when the API host returns a redirect we refuse to follow (SSRF guard)."""


@dataclasses.dataclass
class DelightedResumeConfig:
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    # Delighted uses Basic auth with the API key as the username and a blank password.
    token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for Delighted's time filters.

    Delighted stores and filters timestamps as epoch seconds, so the persisted watermark is
    already an int in the common case; datetimes are accepted defensively.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_delighted_url(url: str) -> bool:
    """Whether ``url`` points at the Delighted API host over HTTPS.

    Pagination/resume URLs are server-controlled (Link header / state store), so we pin them to
    the API host to avoid forwarding the Authorization header to an arbitrary address (SSRF).
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and (parsed.hostname or "").lower() == DELIGHTED_HOST
    except Exception:
        return False


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{DELIGHTED_BASE_URL}{path}"
    return f"{DELIGHTED_BASE_URL}{path}?{urlencode(clean_params)}"


def _build_params(
    config: DelightedEndpointConfig,
    incremental_field: Optional[str],
    since_value: Optional[int],
) -> dict[str, Any]:
    if config.pagination == "none":
        return {}

    params: dict[str, Any] = {"per_page": PAGE_SIZE, **config.extra_params}

    # Ascending order on the cursor field keeps already-fetched pages stable and lets the
    # incremental watermark advance monotonically. Only survey_responses documents an
    # `order` param; the other list endpoints return oldest-first by default.
    order = config.default_order
    if incremental_field is not None:
        order = config.order_param_map.get(incremental_field, order)
    if order is not None:
        params["order"] = order

    if since_value is not None and incremental_field is not None:
        param_name = config.incremental_param_map.get(incremental_field)
        if param_name is not None:
            params[param_name] = since_value

    return params


def _next_page_url(url: str) -> str:
    """Return the same URL with its `page` query param incremented (default page is 1)."""
    scheme, netloc, path, query, fragment = urlsplit(url)
    query_params = {key: values[-1] for key, values in parse_qs(query).items()}
    current_page = int(query_params.get("page", "1"))
    query_params["page"] = str(current_page + 1)
    return urlunsplit((scheme, netloc, path, urlencode(query_params), fragment))


def _next_url(
    response: requests.Response, current_url: str, items_count: int, config: DelightedEndpointConfig
) -> Optional[str]:
    # Prefer an explicit Link header cursor (people uses RFC 5988 `rel="next"`); fall back to
    # page-number increments for page/per_page endpoints. The page-based endpoints signal the
    # end of results only by returning a short page, so a final empty page may be fetched when
    # the row count is an exact multiple of the page size.
    link_next = response.links.get("next", {}).get("url")
    if link_next and _is_delighted_url(link_next):
        return link_next

    if config.pagination == "page" and items_count == PAGE_SIZE:
        return _next_page_url(current_url)

    return None


def _parse_retry_after(response: requests.Response) -> Optional[float]:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return max(float(header), 0.0)
    except (TypeError, ValueError):
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exception, DelightedRetryableError) and exception.retry_after is not None:
        return min(exception.retry_after, MAX_RETRY_AFTER_SECONDS)
    return wait_exponential_jitter(initial=1, max=60)(retry_state)


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid. /v1/metrics.json is a cheap authenticated probe."""
    try:
        response = make_tracked_session().get(
            f"{DELIGHTED_BASE_URL}/metrics.json",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DelightedResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DELIGHTED_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    since_value = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None
    cursor_field = incremental_field if should_use_incremental_field else None

    @retry(
        retry=retry_if_exception_type((DelightedRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> requests.Response:
        # Don't follow redirects: a 3xx from the API host could point at an internal address,
        # bypassing the host validation done before the request and leaking the API key (SSRF).
        response = make_tracked_session().get(
            page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise DelightedRetryableError(
                f"Delighted API error (retryable): status={response.status_code}, url={page_url}",
                retry_after=_parse_retry_after(response),
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
        # silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise DelightedUnexpectedRedirectError(
                f"Delighted API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"Delighted API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    if config.pagination == "none":
        data = fetch_page(_build_url(config.path, {})).json()
        rows = data if isinstance(data, list) else [data]
        if rows:
            yield rows
        return

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_delighted_url(resume_config.next_url):
        url: str = resume_config.next_url
        logger.debug(f"Delighted: resuming from URL: {url}")
    else:
        if resume_config is not None:
            logger.warning("Delighted: ignoring resume URL whose host does not match the Delighted API host")
        url = _build_url(config.path, _build_params(config, cursor_field, since_value))

    while True:
        response = fetch_page(url)
        data = response.json()
        items = data if isinstance(data, list) else []

        if items:
            yield items

        next_url = _next_url(response, url, len(items), config)
        if not next_url:
            break

        resumable_source_manager.save_state(DelightedResumeConfig(next_url=next_url))
        url = next_url


def delighted_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DelightedResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = DELIGHTED_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key] if config.primary_key else None,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
