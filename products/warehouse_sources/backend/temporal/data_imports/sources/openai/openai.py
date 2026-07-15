import hashlib
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
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.settings import (
    OPENAI_ENDPOINTS,
    OpenAIEndpointConfig,
    PaginationType,
)

OPENAI_BASE_URL = "https://api.openai.com"
# Entity list endpoints allow up to 100 per page.
ENTITY_PAGE_SIZE = 100
# Floor for the required `start_time` on a full refresh. The OpenAI API launched in mid-2020, so no
# usage or cost data can predate this — starting here rather than the epoch avoids requesting
# decades of empty buckets while still pulling all available history.
DEFAULT_START_TIME = datetime(2020, 1, 1, tzinfo=UTC)


class OpenAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class OpenAIResumeConfig:
    # Opaque pagination cursor: an `after` object id for CURSOR endpoints or a `next_page` token
    # for PAGE endpoints. None means "start at the first page".
    cursor: str | None = None
    # Project fan-out only: the project whose resources we were paging when we saved state. A
    # stable id (not a positional index) so projects added/removed between a crash and the retry
    # can't resume us into the wrong project.
    project_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> int:
    """Convert an incremental watermark (datetime/date/int) to the Unix seconds the API expects."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _from_unix_seconds(value: Any) -> datetime | None:
    """Convert an epoch-seconds field to a UTC datetime so the column lands as a real timestamp
    (needed for the DateTime incremental watermark and datetime partitioning)."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _build_url(path: str, params: dict[str, Any], multi_params: dict[str, list[str]] | None = None) -> str:
    """Build a fully-encoded URL. `multi_params` values are repeated (e.g. group_by=a&group_by=b),
    matching the official SDK's query serialization."""
    query: list[tuple[str, str]] = [(k, str(v)) for k, v in params.items() if v is not None]
    if multi_params:
        for key, values in multi_params.items():
            query.extend((key, v) for v in values)
    encoded = urlencode(query)
    url = f"{OPENAI_BASE_URL}{path}"
    return f"{url}?{encoded}" if encoded else url


@retry(
    retry=retry_if_exception_type(
        (
            OpenAIRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    # The usage/costs endpoints have low (undocumented) rate limits, so back off generously on 429.
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise OpenAIRetryableError(f"OpenAI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"OpenAI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the smallest list endpoint confirms the admin key is genuine.
    url = _build_url("/v1/organization/projects", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False
    # 200 => valid. 403 => valid key without a scope we probed here; still a real key, so accept it
    # at create time (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    return response.status_code in (200, 403)


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a usage/costs bucket row.

    Hashes only the identity/dimension fields (never the metric values), so a bucket whose metrics
    get restated between runs keeps the same id and merge updates it in place rather than inserting
    a duplicate.
    """
    # Use a sentinel for None so a missing dimension can never collide with an empty-string value.
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _flatten_bucket_result(
    config: OpenAIEndpointConfig, bucket: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Flatten one grouped result inside a time bucket into a row.

    Metric fields vary per endpoint (tokens, images, seconds, ...), so everything except `object`
    is copied through; single-level nested objects (costs' `amount: {value, currency}`) become
    `<key>_<subkey>` columns.
    """
    row: dict[str, Any] = {
        "id": _row_id(bucket.get("start_time"), *(result.get(dim) for dim in config.group_by)),
        "start_time": _from_unix_seconds(bucket.get("start_time")),
        "end_time": _from_unix_seconds(bucket.get("end_time")),
    }
    for key, value in result.items():
        if key == "object":
            continue
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                row[f"{key}_{sub_key}"] = sub_value
        else:
            row[key] = value
    return row


def _flatten_owner(item: dict[str, Any]) -> dict[str, Any]:
    """API keys carry a nested `owner` object; surface its identity as flat columns.

    Project API keys nest the principal one level deeper (`owner.user` / `owner.service_account`);
    admin API keys carry the fields directly on `owner`.
    """
    owner = item.get("owner")
    if not isinstance(owner, dict):
        return item
    item = {**item}
    item.pop("owner")
    principal = owner.get("user") or owner.get("service_account")
    if not isinstance(principal, dict):
        principal = owner
    item["owner_type"] = owner.get("type")
    item["owner_id"] = principal.get("id")
    item["owner_name"] = principal.get("name")
    return item


def _normalize_entity(endpoint: str, item: dict[str, Any]) -> dict[str, Any]:
    if endpoint in ("admin_api_keys", "project_api_keys"):
        return _flatten_owner(item)
    if endpoint == "audit_logs":
        return _normalize_audit_log(item)
    return item


def _normalize_audit_log(item: dict[str, Any]) -> dict[str, Any]:
    """Give audit log rows a stable column set.

    Each event carries its details under a key named after the event type (e.g. `project.created`),
    which would otherwise fan out into one sparse column per event type; fold it into a single
    `event_data` column instead. `effective_at` becomes a real timestamp for the incremental
    watermark and partitioning.
    """
    item = {**item}
    event_type = item.get("type")
    if isinstance(event_type, str) and event_type in item:
        item["event_data"] = item.pop(event_type)
    item["effective_at"] = _from_unix_seconds(item.get("effective_at"))
    return item


def _bucket_params(
    config: OpenAIEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    params: dict[str, Any] = {"bucket_width": config.bucket_width}
    if config.limit is not None:
        params["limit"] = config.limit

    # `start_time` is required. On an incremental run start from the watermark (already shifted
    # back by the pipeline's lookback); otherwise fall back to the API launch era to pull all
    # available history.
    if should_use_incremental_field and db_incremental_field_last_value:
        params["start_time"] = _to_unix_seconds(db_incremental_field_last_value)
    else:
        params["start_time"] = _to_unix_seconds(DEFAULT_START_TIME)

    multi_params = {"group_by": config.group_by} if config.group_by else {}
    return params, multi_params


def _iter_bucket_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
    config: OpenAIEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    params, multi_params = _bucket_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.cursor:
        params["page"] = resume.cursor
        logger.debug(f"OpenAI: resuming {config.name} from page cursor")

    while True:
        url = _build_url(config.path, params, multi_params)
        data = _fetch_page(session, url, headers, logger)
        next_page = data.get("next_page")
        has_more = bool(data.get("has_more"))
        buckets = data.get("data", [])

        for bucket in buckets:
            for result in bucket.get("results", []):
                batcher.batch(_flatten_bucket_result(config, bucket, result))
                # A single batch can split into several ready chunks, so drain them all before
                # the next batch() call (which raises if `_ready` is still populated).
                while batcher.should_yield():
                    yield batcher.get_table()
                    # Save only when a batch is actually committed, pointing at the next page. A
                    # crash then resumes from a page whose predecessors are all in the yielded
                    # batch, so no buffered rows are skipped; the overlap merge dedupes on the
                    # primary key.
                    if has_more and next_page:
                        resumable_source_manager.save_state(OpenAIResumeConfig(cursor=next_page))

        # The costs endpoint is known to sometimes return a next_page token for an empty page;
        # treat an empty page as the end of the stream rather than looping on it.
        if not buckets:
            if has_more:
                logger.debug(f"OpenAI: {config.name} returned an empty page with has_more=true, stopping pagination")
            break
        if not has_more or not next_page:
            break
        params["page"] = next_page


def _iter_cursor_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    base_params: dict[str, Any],
    start_after: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield (items, last_id) for each page of a cursor-paginated entity endpoint."""
    after = start_after
    while True:
        params = {**base_params, "limit": ENTITY_PAGE_SIZE}
        if after:
            params["after"] = after
        url = _build_url(path, params)
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", [])
        # Fall back to the last item's id: `last_id` isn't documented on every list response.
        last_id = data.get("last_id") or (items[-1].get("id") if items else None)
        yield items, last_id

        if not data.get("has_more") or not last_id:
            break
        after = last_id


def _iter_entity_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
    config: OpenAIEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    base_params: dict[str, Any] = {**config.extra_params}
    if config.name == "audit_logs" and should_use_incremental_field and db_incremental_field_last_value:
        # Bracket-style nested param, matching the official SDK's query serialization. `gte` (not
        # `gt`) so same-second events that landed after the watermark was cut aren't skipped;
        # merge dedupes the boundary overlap on `id`.
        base_params["effective_at[gte]"] = _to_unix_seconds(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_after = resume.cursor if resume is not None else None

    for items, last_id in _iter_cursor_pages(session, headers, logger, config.path, base_params, start_after):
        for item in items:
            batcher.batch(_normalize_entity(config.name, item))
            while batcher.should_yield():
                yield batcher.get_table()
                if last_id:
                    resumable_source_manager.save_state(OpenAIResumeConfig(cursor=last_id))


def _iter_project_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
    config: OpenAIEndpointConfig,
) -> Iterator[Any]:
    """Fan out over every project, emitting the project id on each row for the composite key."""
    project_ids = _list_all_project_ids(session, headers, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = project_ids
    resume_after: str | None = None
    if resume is not None and resume.project_id and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_after = resume.cursor
        logger.debug(f"OpenAI: resuming {config.name} from project_id={resume.project_id}")

    for index, project_id in enumerate(remaining):
        path = config.path.format(project_id=project_id)
        after = resume_after
        resume_after = None  # only the resumed-into project uses the saved cursor

        for items, last_id in _iter_cursor_pages(session, headers, logger, path, {}, after):
            for item in items:
                row = {**_normalize_entity(config.name, item), "project_id": project_id}
                batcher.batch(row)
                while batcher.should_yield():
                    yield batcher.get_table()
                    if last_id:
                        resumable_source_manager.save_state(OpenAIResumeConfig(cursor=last_id, project_id=project_id))

        # Flush any incomplete batch before checkpointing to the next project, otherwise a crash
        # between the state save and the final flush would drop this project's buffered rows.
        while batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(OpenAIResumeConfig(cursor=None, project_id=remaining[index + 1]))


def _list_all_project_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    project_ids: list[str] = []
    for items, _ in _iter_cursor_pages(
        session, headers, logger, "/v1/organization/projects", {"include_archived": "true"}
    ):
        project_ids.extend(item["id"] for item in items if item.get("id"))
    return project_ids


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = OPENAI_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=5000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    if config.pagination == PaginationType.PAGE:
        yield from _iter_bucket_rows(
            session,
            headers,
            logger,
            batcher,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out_over_projects:
        yield from _iter_project_fan_out_rows(session, headers, logger, batcher, resumable_source_manager, config)
    else:
        yield from _iter_entity_rows(
            session,
            headers,
            logger,
            batcher,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    while batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def openai_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENAI_ENDPOINTS[endpoint]

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
