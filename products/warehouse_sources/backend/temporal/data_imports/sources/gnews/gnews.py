import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.settings import (
    GNEWS_ENDPOINTS,
    MAX_ARTICLES_PER_QUERY,
    PAGE_SIZE,
    GNewsEndpointConfig,
)

GNEWS_BASE_URL = "https://gnews.io/api/v4"

# 1000-article ceiling divided by the page size — the last page we'll ever request for one query.
MAX_PAGES = -(-MAX_ARTICLES_PER_QUERY // PAGE_SIZE)


class GNewsRetryableError(Exception):
    pass


@dataclasses.dataclass
class GNewsResumeConfig:
    # Page number to resume from. Checkpointed as the current (not next) page so a crash re-fetches
    # the in-flight page and re-yields it — merge dedupes the overlap on the `url` primary key.
    next_page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    # Auth via header rather than the `apikey` query param so the key never lands in a logged URL.
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _format_from_value(value: Any) -> str | None:
    """Format an incremental cursor as GNews's ISO 8601 `from` filter (`YYYY-MM-DDTHH:MM:SSZ`).

    A future-dated cursor would filter out every article, so cap it at now — asking for articles
    published after now is a no-op and keeps the request valid.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        dt = min(dt.astimezone(UTC), now)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        dt = min(dt, now)
    else:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_params(
    config: GNewsEndpointConfig,
    query: str | None,
    category: str | None,
    language: str | None,
    country: str | None,
    from_value: str | None,
    page: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {"max": PAGE_SIZE, "sortby": "publishedAt", "page": page}
    if config.path == "/search":
        # /search requires the q keyword param (max 200 chars).
        params["q"] = (query or "")[:200]
    elif category:
        params["category"] = category
    if language:
        params["lang"] = language
    if country:
        params["country"] = country
    if from_value:
        params["from"] = from_value
    return params


def _build_url(config: GNewsEndpointConfig, params: dict[str, Any]) -> str:
    return f"{GNEWS_BASE_URL}{config.path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            GNewsRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (quota/rate limit) and 5xx are transient; retry with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise GNewsRetryableError(f"GNews API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"GNews API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # Probe /top-headlines (no keyword required) with the smallest possible page. GNews has no
    # per-endpoint scopes, so a single probe confirms the key for every table.
    url = _build_url(GNEWS_ENDPOINTS["top_headlines"], {"category": "general", "max": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (400, 401):
        return False, "Invalid GNews API key"
    if response.status_code == 403:
        return False, "Your GNews plan does not permit this request, or its daily request quota is exhausted"
    try:
        errors = response.json().get("errors")
        if errors:
            return False, errors[0] if isinstance(errors, list) else str(errors)
    except (ValueError, TypeError):
        pass
    return False, response.text


def _flatten_article(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested `source` object onto the row so the table has flat columns."""
    source = item.pop("source", None)
    if isinstance(source, dict):
        item["source_id"] = source.get("id")
        item["source_name"] = source.get("name")
        item["source_url"] = source.get("url")
        item["source_country"] = source.get("country")
    return item


def get_rows(
    api_key: str,
    endpoint: str,
    query: str | None,
    category: str | None,
    language: str | None,
    country: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GNewsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = GNEWS_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    from_value = (
        _format_from_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume:
        logger.debug(f"GNews: resuming {endpoint} from page {page}")

    while True:
        url = _build_url(config, _build_params(config, query, category, language, country, from_value, page))

        try:
            data = _fetch_page(session, url, headers, logger)
        except requests.HTTPError as exc:
            # GNews rejects pagination beyond page 1 on plans that don't allow it (403). We already
            # have page 1, so stop cleanly rather than failing the whole sync. A 403 on the first
            # page is a genuine quota/permission error and is re-raised.
            if exc.response is not None and exc.response.status_code == 403 and page > 1:
                logger.warning(f"GNews: pagination not available past page {page - 1} on this plan, stopping")
                break
            raise

        articles = data.get("articles", [])
        if not articles:
            break

        # A short page is the last page; MAX_PAGES caps us at the server's 1000-article ceiling.
        is_last_page = len(articles) < PAGE_SIZE or page >= MAX_PAGES
        checkpoint_page = page
        for item in articles:
            batcher.batch(_flatten_article(item))
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more pages remain) so a crash re-yields this
                # page instead of skipping it, without pointlessly re-fetching the final page.
                if not is_last_page:
                    resumable_source_manager.save_state(GNewsResumeConfig(next_page=checkpoint_page))

        if is_last_page:
            break
        page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def gnews_source(
    api_key: str,
    endpoint: str,
    query: str | None,
    category: str | None,
    language: str | None,
    country: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GNewsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = GNEWS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            query=query,
            category=category,
            language=language,
            country=country,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # GNews only offers newest-first ordering (sortby=publishedAt), so rows always arrive desc.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
