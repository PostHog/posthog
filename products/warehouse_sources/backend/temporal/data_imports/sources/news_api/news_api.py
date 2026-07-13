import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.settings import (
    NEWS_API_ENDPOINTS,
    NewsApiEndpointConfig,
)

NEWS_API_BASE_URL = "https://newsapi.org"

# NewsAPI caps pageSize at 100 and total reachable results per query window at 100. A page cap is a
# defensive backstop in case a paid plan lets pagination run further than expected.
PAGE_SIZE = 100
MAX_PAGES = 100

# NewsAPI error codes that are permanent config errors (not transient) — stop paginating without
# raising, so a full sync of the reachable window still completes.
_TERMINAL_RESULT_CODES = {"maximumResultsReached"}


class NewsApiRetryableError(Exception):
    pass


@dataclasses.dataclass
class NewsApiResumeConfig:
    # Next page number to request. Pagination is 1-indexed; resume picks up mid-endpoint after a
    # heartbeat timeout without restarting from page 1.
    next_page: int


def _get_headers(api_key: str) -> dict[str, str]:
    # Header auth avoids leaking the key into request URLs / logs (the apiKey query param is the
    # documented alternative). `Accept` keeps NewsAPI on its JSON contract.
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _format_from_value(value: Any) -> str | None:
    """Format an incremental cursor value for NewsAPI's `from` param (ISO 8601)."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _build_params(
    config: NewsApiEndpointConfig,
    query: str,
    language: str | None,
    page: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    # /v2/top-headlines/sources takes no query/pagination — only optional facet filters.
    if config.name == "sources":
        if language:
            params["language"] = language
        return params

    if query:
        params["q"] = query
    if config.paginated:
        params["pageSize"] = PAGE_SIZE
        params["page"] = page

    if config.name == "everything":
        # publishedAt is the only sort NewsAPI exposes for /v2/everything; it returns newest-first
        # (descending), which is why the SourceResponse below declares sort_mode="desc".
        params["sortBy"] = "publishedAt"
        # `language` is only a valid filter on /v2/everything (top-headlines uses country/category).
        if language:
            params["language"] = language
        if config.supports_incremental and should_use_incremental_field:
            from_value = _format_from_value(db_incremental_field_last_value)
            if from_value:
                params["from"] = from_value

    return params


def validate_credentials(api_key: str) -> bool:
    # /v2/top-headlines/sources is the cheapest probe: it needs only a valid key (no query params),
    # so it confirms the token without spending a search request.
    url = f"{NEWS_API_BASE_URL}/v2/top-headlines/sources"
    try:
        session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
        response = session.get(url, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            NewsApiRetryableError,
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
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # NewsAPI rate-limits with 429 and returns 5xx on transient outages — both worth retrying.
    if response.status_code == 429 or response.status_code >= 500:
        raise NewsApiRetryableError(f"NewsAPI error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"NewsAPI error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    query: str,
    language: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewsApiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NEWS_API_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # redact_values scrubs the key from tracked telemetry / captured samples — the X-Api-Key header
    # value isn't reliably redacted by header name alone.
    session = make_tracked_session(redact_values=(api_key,))

    # Non-paginated endpoints (sources) return everything in one response — no resume state.
    if not config.paginated:
        url = f"{NEWS_API_BASE_URL}{config.path}"
        params = _build_params(
            config, query, language, 1, should_use_incremental_field, db_incremental_field_last_value
        )
        if params:
            url = f"{url}?{urlencode(params)}"
        data = _fetch_page(session, url, headers, logger)
        rows = data.get(config.data_key, [])
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1

    while page <= MAX_PAGES:
        params = _build_params(
            config, query, language, page, should_use_incremental_field, db_incremental_field_last_value
        )
        url = f"{NEWS_API_BASE_URL}{config.path}?{urlencode(params)}"

        try:
            data = _fetch_page(session, url, headers, logger)
        except requests.HTTPError as exc:
            # NewsAPI returns 426 with code `maximumResultsReached` once pagination hits the reachable
            # cap. That's a normal terminal condition for the query window, not a failure — stop cleanly.
            code = _error_code(exc)
            if code in _TERMINAL_RESULT_CODES:
                logger.info(f"NewsAPI: reached result cap for endpoint={endpoint} at page={page}, stopping")
                break
            raise

        rows = data.get(config.data_key, [])
        if not rows:
            break

        yield rows

        total_results = data.get("totalResults") or 0
        # Stop when we've drained the reachable set: a short final page, or (when the API reports a
        # positive total) we've paged past it. Guard on `total_results` so a missing/zero total on a
        # full page doesn't stop us early and silently drop later pages — the short-page check,
        # MAX_PAGES cap, and `maximumResultsReached` still bound the walk.
        if len(rows) < PAGE_SIZE or (total_results and page * PAGE_SIZE >= total_results):
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        resumable_source_manager.save_state(NewsApiResumeConfig(next_page=page))


def _error_code(exc: requests.HTTPError) -> str | None:
    """Pull NewsAPI's machine-readable `code` out of an error response body, if present."""
    # `HTTPError.response` is typed non-optional but is None at runtime when the error carries no
    # response, so read it defensively via getattr rather than trusting the annotation.
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        return response.json().get("code")
    except ValueError:
        return None


def news_api_source(
    api_key: str,
    endpoint: str,
    query: str,
    language: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewsApiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NEWS_API_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            query=query,
            language=language,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # /v2/everything returns newest-first, so the incremental endpoint must declare desc or the
        # pipeline would corrupt the watermark. The full-refresh endpoints don't track a watermark,
        # so their arrival order is immaterial — leave them on the default.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
