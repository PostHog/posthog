import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.settings import (
    INCREMENTAL_PARAM_BY_FIELD,
    SCALE_AI_ENDPOINTS,
    ScaleAIEndpointConfig,
)

SCALE_AI_BASE_URL = "https://api.scale.com/v1"


class ScaleAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class ScaleAIResumeConfig:
    # Cursor token for the `tasks` endpoint. Holds the token used to fetch the page currently
    # being processed, so a resume re-fetches that page (merge dedupes on the primary key) rather
    # than skipping the un-yielded remainder of it. None means "start from the first page".
    next_token: str | None = None
    # Offset for the `batches` endpoint, pointing at the page currently being processed for the
    # same re-fetch-on-resume reason.
    offset: int | None = None


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as an ISO 8601 string, which Scale's time filters expect."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _auth(api_key: str) -> tuple[str, str]:
    """Scale uses HTTP Basic auth with the API key as the username and an empty password."""
    return (api_key, "")


def _extract_docs(data: Any) -> list[dict[str, Any]]:
    """Pull the list of records out of a Scale list response.

    Tasks/batches wrap results in a `docs` envelope; projects return a bare array. Handle both
    (plus a defensive fallback) so a shape difference between endpoints stays contained here.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("docs", "projects", "batches", "tasks"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


@retry(
    retry=retry_if_exception_type(
        (
            ScaleAIRetryableError,
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
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=60)

    # Scale publishes no documented rate limit; treat 429 and 5xx as transient and back off.
    if response.status_code == 429 or response.status_code >= 500:
        raise ScaleAIRetryableError(f"Scale API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Scale API error: status={response.status_code}, body={response.text}, url={url}")
        # 401/403 surface here as an HTTPError; get_non_retryable_errors matches on the status text.
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    """One cheap probe against the tasks list endpoint to confirm the API key is genuine."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{SCALE_AI_BASE_URL}/tasks",
            params={"limit": 1},
            auth=_auth(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def _build_params(
    config: ScaleAIEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.pagination in ("cursor", "offset"):
        params["limit"] = config.page_size

    if should_use_incremental_field and db_incremental_field_last_value:
        chosen = incremental_field or config.default_incremental_field
        param_name = INCREMENTAL_PARAM_BY_FIELD.get(chosen) if chosen else None
        if param_name:
            params[param_name] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _iter_cursor(
    session: requests.Session,
    url: str,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[ScaleAIResumeConfig],
    resume: ScaleAIResumeConfig | None,
) -> Iterator[Any]:
    """Paginate a `next_token` cursor endpoint (tasks).

    The incremental `updated_after` filter in `base_params` is documented as server-side, so the
    result set is already bounded and pagination terminates when `next_token` is null (verified from
    docs; not curl-verified against a live key). If a future check finds the filter only applies to
    the first page, this loop would need a client-side stop once a page predates the watermark.
    """
    current_token = resume.next_token if resume is not None else None

    while True:
        params = dict(base_params)
        if current_token:
            params["next_token"] = current_token

        data = _fetch_page(session, url, params, logger)
        docs = _extract_docs(data)
        next_token = data.get("next_token") if isinstance(data, dict) else None

        for item in docs:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Checkpoint the CURRENT page token so a crash re-fetches this page rather than
                # skipping its un-yielded remainder; merge dedupes the overlap on the primary key.
                manager.save_state(ScaleAIResumeConfig(next_token=current_token))

        if not next_token or not docs:
            break
        current_token = next_token


def _iter_offset(
    session: requests.Session,
    url: str,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[ScaleAIResumeConfig],
    resume: ScaleAIResumeConfig | None,
    page_size: int,
) -> Iterator[Any]:
    """Paginate a `limit`/`offset` endpoint (batches)."""
    offset = resume.offset if resume is not None and resume.offset is not None else 0

    while True:
        params = {**base_params, "offset": offset}
        data = _fetch_page(session, url, params, logger)
        docs = _extract_docs(data)
        if not docs:
            break

        for item in docs:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                manager.save_state(ScaleAIResumeConfig(offset=offset))

        # A short page is the last page; a full page means another may follow.
        if len(docs) < page_size:
            break
        offset += page_size


def _iter_single(
    session: requests.Session,
    url: str,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    batcher: Batcher,
) -> Iterator[Any]:
    """Fetch a single, non-paginated list (projects)."""
    data = _fetch_page(session, url, base_params, logger)
    for item in _extract_docs(data):
        batcher.batch(item)
        if batcher.should_yield():
            yield batcher.get_table()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ScaleAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = SCALE_AI_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,))
    session.auth = _auth(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    base_params = _build_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    url = f"{SCALE_AI_BASE_URL}{config.path}"
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "cursor":
        yield from _iter_cursor(session, url, base_params, logger, batcher, resumable_source_manager, resume)
    elif config.pagination == "offset":
        yield from _iter_offset(
            session, url, base_params, logger, batcher, resumable_source_manager, resume, config.page_size
        )
    else:
        yield from _iter_single(session, url, base_params, logger, batcher)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def scale_ai_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ScaleAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SCALE_AI_ENDPOINTS[endpoint]

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
        primary_keys=endpoint_config.primary_keys,
        # Scale returns every list endpoint newest-first by created_at and exposes no sort control,
        # so rows always arrive descending. "desc" persists the incremental watermark only at
        # successful job end, which is correct here: tasks filter on updated_at but arrive in
        # created_at order, so a per-batch (asc) watermark could advance past unread rows.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
