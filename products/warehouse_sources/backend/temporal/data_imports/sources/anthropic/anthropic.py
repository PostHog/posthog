import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANTHROPIC_ENDPOINTS,
    AnthropicEndpointConfig,
    PaginationType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
# Entity list endpoints allow up to 1000 per page.
ENTITY_PAGE_SIZE = 1000
# Floor for the required `starting_at` on a full refresh. Anthropic launched in 2023, so no usage or
# cost data can predate this — starting here rather than the epoch avoids requesting decades of empty
# buckets while still pulling all available history.
DEFAULT_STARTING_AT = datetime(2023, 1, 1, tzinfo=UTC)


class AnthropicRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        # Seconds the server asked us to wait (from a 429 `Retry-After`), or None to back off blindly.
        self.retry_after = retry_after


# The report endpoints (usage_report/cost_report) are strictly rate limited and return a `Retry-After`
# on 429. Cap the honored value so a pathological header can't pin the worker; the pipeline retries the
# activity above us if the window is genuinely longer.
_MAX_RETRY_AFTER_SECONDS = 60
_fallback_wait = wait_exponential_jitter(initial=1, max=30)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a `Retry-After` header expressed as delta-seconds (Anthropic's form). Returns None for a
    missing, non-numeric, or negative value so the caller falls back to exponential backoff."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _wait_anthropic(retry_state: RetryCallState) -> float:
    """Honor the server's `Retry-After` on 429s (capped), else fall back to exponential jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, AnthropicRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, _MAX_RETRY_AFTER_SECONDS)
    return _fallback_wait(retry_state)


@dataclasses.dataclass
class AnthropicResumeConfig:
    # Opaque pagination cursor: an `after_id` for CURSOR endpoints or a `next_page` token for PAGE
    # endpoints. None means "start at the first page".
    cursor: str | None = None
    # workspace_members fan-out only: the workspace whose members we were paging when we saved state.
    # A stable id (not a positional index) so workspaces added/removed between a crash and the retry
    # can't resume us into the wrong workspace.
    workspace_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "accept": "application/json",
    }


def _format_rfc3339(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp with a Z suffix (Anthropic's format)."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_url(path: str, params: dict[str, Any], multi_params: dict[str, list[str]] | None = None) -> str:
    """Build a fully-encoded URL. `multi_params` values are repeated (e.g. group_by[]=a&group_by[]=b)."""
    query: list[tuple[str, str]] = [(k, str(v)) for k, v in params.items() if v is not None]
    if multi_params:
        for key, values in multi_params.items():
            query.extend((key, v) for v in values)
    encoded = urlencode(query)
    url = f"{ANTHROPIC_BASE_URL}{path}"
    return f"{url}?{encoded}" if encoded else url


@retry(
    retry=retry_if_exception_type(
        (
            AnthropicRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_wait_anthropic,
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response.headers.get("retry-after")) if response.status_code == 429 else None
        raise AnthropicRetryableError(
            f"Anthropic API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    if not response.ok:
        logger.error(f"Anthropic API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the smallest list endpoint confirms the admin key is genuine.
    url = _build_url("/v1/organizations/users", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False
    # 200 => valid. 403 => valid key without a scope we probed here; still a real key, so accept it at
    # create time (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    return response.status_code in (200, 403)


def _flatten_created_by(item: dict[str, Any]) -> dict[str, Any]:
    """api_keys carry a nested `created_by: {id, type}`; surface it as flat columns."""
    created_by = item.get("created_by")
    if isinstance(created_by, dict):
        item = {**item}
        item.pop("created_by")
        item["created_by_id"] = created_by.get("id")
        item["created_by_type"] = created_by.get("type")
    return item


def _normalize_entity(endpoint: str, item: dict[str, Any]) -> dict[str, Any]:
    if endpoint == "api_keys":
        return _flatten_created_by(item)
    return item


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a report row.

    Hashes only the identity/dimension fields (never the metric values), so a bucket whose metrics
    get restated between runs keeps the same id and merge updates it in place rather than inserting a
    duplicate.
    """
    # Use a sentinel for None so a missing dimension can never collide with an empty-string value.
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _flatten_usage_result(bucket: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    starting_at = bucket.get("starting_at")
    cache_creation = result.get("cache_creation") or {}
    server_tool_use = result.get("server_tool_use") or {}
    row = {
        "id": _row_id(
            starting_at,
            result.get("account_id"),
            result.get("api_key_id"),
            result.get("service_account_id"),
            result.get("workspace_id"),
            result.get("model"),
            result.get("service_tier"),
            result.get("context_window"),
            result.get("inference_geo"),
        ),
        "starting_at": starting_at,
        "ending_at": bucket.get("ending_at"),
        "account_id": result.get("account_id"),
        "api_key_id": result.get("api_key_id"),
        "service_account_id": result.get("service_account_id"),
        "workspace_id": result.get("workspace_id"),
        "model": result.get("model"),
        "service_tier": result.get("service_tier"),
        "context_window": result.get("context_window"),
        "inference_geo": result.get("inference_geo"),
        "uncached_input_tokens": result.get("uncached_input_tokens"),
        "cache_read_input_tokens": result.get("cache_read_input_tokens"),
        "cache_creation_ephemeral_1h_input_tokens": cache_creation.get("ephemeral_1h_input_tokens"),
        "cache_creation_ephemeral_5m_input_tokens": cache_creation.get("ephemeral_5m_input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "web_search_requests": server_tool_use.get("web_search_requests"),
    }
    return row


def _flatten_cost_result(bucket: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    starting_at = bucket.get("starting_at")
    return {
        "id": _row_id(
            starting_at,
            result.get("workspace_id"),
            result.get("description"),
            result.get("cost_type"),
            result.get("model"),
            result.get("service_tier"),
            result.get("token_type"),
            result.get("context_window"),
        ),
        "starting_at": starting_at,
        "ending_at": bucket.get("ending_at"),
        "workspace_id": result.get("workspace_id"),
        "description": result.get("description"),
        "cost_type": result.get("cost_type"),
        "model": result.get("model"),
        "service_tier": result.get("service_tier"),
        "token_type": result.get("token_type"),
        "context_window": result.get("context_window"),
        "currency": result.get("currency"),
        "amount": result.get("amount"),
    }


def _report_params(
    config: AnthropicEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    params: dict[str, Any] = {"bucket_width": config.bucket_width}
    if config.limit is not None:
        params["limit"] = config.limit

    # `starting_at` is required. On an incremental run start from the watermark (already shifted back
    # by the pipeline's lookback); otherwise fall back to the Anthropic launch date to pull all history.
    if should_use_incremental_field and db_incremental_field_last_value:
        params["starting_at"] = _format_rfc3339(db_incremental_field_last_value)
    else:
        params["starting_at"] = _format_rfc3339(DEFAULT_STARTING_AT)

    multi_params = {"group_by[]": config.group_by} if config.group_by else {}
    return params, multi_params


def _iter_report_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    config: AnthropicEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    params, multi_params = _report_params(config, should_use_incremental_field, db_incremental_field_last_value)
    flatten = _flatten_usage_result if config.name == "usage_report" else _flatten_cost_result

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.cursor:
        params["page"] = resume.cursor
        logger.debug(f"Anthropic: resuming {config.name} from page cursor")

    while True:
        url = _build_url(config.path, params, multi_params)
        data = _fetch_page(session, url, headers, logger)
        next_page = data.get("next_page")
        has_more = bool(data.get("has_more"))

        for bucket in data.get("data", []):
            for result in bucket.get("results", []):
                batcher.batch(flatten(bucket, result))
                # A single batch can split into several ready chunks, so drain them all before
                # the next batch() call (which raises if `_ready` is still populated).
                while batcher.should_yield():
                    yield batcher.get_table()
                    # Save only when a batch is actually committed, pointing at the next page. A crash
                    # then resumes from a page whose predecessors are all in the yielded batch, so no
                    # buffered rows are skipped; the overlap merge dedupes on the primary key.
                    if has_more and next_page:
                        resumable_source_manager.save_state(AnthropicResumeConfig(cursor=next_page))

        if not has_more or not next_page:
            break
        params["page"] = next_page


def _iter_cursor_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    base_params: dict[str, Any],
    start_after_id: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield (items, last_id) for each page of a cursor-paginated entity endpoint."""
    after_id = start_after_id
    while True:
        params = {**base_params, "limit": ENTITY_PAGE_SIZE}
        if after_id:
            params["after_id"] = after_id
        url = _build_url(path, params)
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", [])
        last_id = data.get("last_id")
        yield items, last_id

        if not data.get("has_more") or not last_id:
            break
        after_id = last_id


def _iter_entity_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    config: AnthropicEndpointConfig,
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_after_id = resume.cursor if resume is not None else None

    for items, last_id in _iter_cursor_pages(
        session, headers, logger, config.path, config.extra_params, start_after_id
    ):
        for item in items:
            batcher.batch(_normalize_entity(config.name, item))
            while batcher.should_yield():
                yield batcher.get_table()
                if last_id:
                    resumable_source_manager.save_state(AnthropicResumeConfig(cursor=last_id))


def _iter_workspace_member_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    config: AnthropicEndpointConfig,
) -> Iterator[Any]:
    """Fan out over every workspace, emitting one row per (workspace_id, user_id) membership."""
    workspace_ids = _list_all_workspace_ids(session, headers, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = workspace_ids
    resume_after_id: str | None = None
    if resume is not None and resume.workspace_id and resume.workspace_id in workspace_ids:
        remaining = workspace_ids[workspace_ids.index(resume.workspace_id) :]
        resume_after_id = resume.cursor
        logger.debug(f"Anthropic: resuming workspace_members from workspace_id={resume.workspace_id}")

    for index, workspace_id in enumerate(remaining):
        path = config.path.format(workspace_id=workspace_id)
        after_id = resume_after_id
        resume_after_id = None  # only the resumed-into workspace uses the saved cursor

        for items, last_id in _iter_cursor_pages(session, headers, logger, path, {}, after_id):
            for item in items:
                # The member object already carries workspace_id, but set it defensively so the
                # composite primary key is always populated.
                row = {**item, "workspace_id": item.get("workspace_id") or workspace_id}
                batcher.batch(row)
                while batcher.should_yield():
                    yield batcher.get_table()
                    if last_id:
                        resumable_source_manager.save_state(
                            AnthropicResumeConfig(cursor=last_id, workspace_id=workspace_id)
                        )

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(AnthropicResumeConfig(cursor=None, workspace_id=remaining[index + 1]))


def _list_all_workspace_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    workspace_ids: list[str] = []
    for items, _ in _iter_cursor_pages(
        session, headers, logger, "/v1/organizations/workspaces", {"include_archived": "true"}
    ):
        workspace_ids.extend(item["id"] for item in items if item.get("id"))
    return workspace_ids


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = ANTHROPIC_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=5000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    if config.pagination == PaginationType.PAGE:
        yield from _iter_report_rows(
            session,
            headers,
            logger,
            batcher,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out_over_workspaces:
        yield from _iter_workspace_member_rows(session, headers, logger, batcher, resumable_source_manager, config)
    else:
        yield from _iter_entity_rows(session, headers, logger, batcher, resumable_source_manager, config)

    while batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def anthropic_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ANTHROPIC_ENDPOINTS[endpoint]

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
        # Report buckets return oldest-first from `starting_at`, and entity cursors page forward, so
        # rows arrive in ascending order — the pipeline checkpoints the watermark after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
