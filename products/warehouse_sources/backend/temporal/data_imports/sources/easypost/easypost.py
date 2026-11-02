from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import EASYPOST_ENDPOINTS

EASYPOST_BASE_URL = "https://api.easypost.com/v2"
# EasyPost caps page_size at 100 across cursor-paginated list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class EasypostRetryableError(Exception):
    pass


@frozen
class EasypostResumeConfig:
    # `before_id` of the page we last yielded. EasyPost paginates newest-first, so advancing the
    # cursor means asking for records created *before* this id. `None` resumes from the first page.
    before_id: str | None = None
    # Same, for endpoints that page oldest-first via `after_id`.
    after_id: str | None = None
    # Path value (e.g. report type) the cursor belongs to, for endpoints walked once per value.
    path_value: str | None = None


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an EasyPost ISO-8601 timestamp (e.g. ``2024-01-15T10:30:00Z``) to an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, str):
        try:
            return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _format_datetime(value: datetime) -> str:
    """Format a datetime for EasyPost's ``start_datetime`` filter (ISO-8601, UTC, ``Z`` suffix)."""
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


@retry_with_deadline(
    retry=retry_if_exception_type((EasypostRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise EasypostRetryableError(f"EasyPost API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"EasyPost API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    """Probe a cheap list endpoint. EasyPost API keys carry full account access (no per-endpoint
    scopes), so a 200 means the key is genuine and active; anything else (401 invalid, 403 inactive)
    is a credential failure."""
    session = make_tracked_session(redact_values=(api_key,))
    session.auth = (api_key, "")
    try:
        response = session.get(
            f"{EASYPOST_BASE_URL}/shipments", params={"page_size": 1}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        return response.status_code == 200
    except Exception:
        return False


def _strip_fields(value: Any, redacted_fields: tuple[str, ...]) -> Any:
    # Recurse so a nested object (a child user's own `children`) cannot carry the field through.
    if isinstance(value, dict):
        return {k: _strip_fields(v, redacted_fields) for k, v in value.items() if k not in redacted_fields}
    if isinstance(value, list):
        return [_strip_fields(v, redacted_fields) for v in value]
    return value


def _redact(items: list[dict[str, Any]], redacted_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not redacted_fields:
        return items
    return _strip_fields(items, redacted_fields)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EasypostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = EASYPOST_ENDPOINTS[endpoint]
    incremental_field_name = incremental_field or "created_at"

    # The fields stripped from rows are secrets; keep the raw responses out of HTTP sample capture too.
    session = make_tracked_session(redact_values=(api_key,), capture=not config.redacted_fields)
    session.auth = (api_key, "")
    collection_key = config.response_key or config.name

    if not config.paginated:
        # Lookup endpoints answer with the whole collection in one response — no cursor and no
        # `has_more`, so there is nothing to resume from or to watermark against.
        data = _fetch_page(session, f"{EASYPOST_BASE_URL}{config.path}", {}, logger)
        collection = data if config.returns_bare_list else data.get(collection_key, [])
        if collection:
            yield _redact(collection, config.redacted_fields)
        return

    # Incremental cursor: EasyPost returns newest-first, so we walk backwards (via `before_id`) and
    # stop once a page reaches the watermark. `start_datetime` filters server-side on `created_at`
    # as an optimization; the client-side stop guarantees correct, bounded behaviour even if the
    # endpoint ignores the filter when combined with cursor pagination.
    last_value_dt: datetime | None = None
    start_datetime: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        last_value_dt = _parse_datetime(db_incremental_field_last_value)
        if last_value_dt is not None and config.supports_start_datetime:
            start_datetime = _format_datetime(last_value_dt)

    path_values: tuple[str | None, ...] = config.path_values or (None,)
    cursor_param = "after_id" if config.ascending else "before_id"
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    cursor_id: str | None = None
    if resume and resume.path_value in path_values:
        start_index = path_values.index(resume.path_value)
        cursor_id = resume.after_id if config.ascending else resume.before_id
    if cursor_id:
        logger.debug(f"EasyPost: resuming {endpoint} from {cursor_param}={cursor_id}")

    for path_value in path_values[start_index:]:
        url = f"{EASYPOST_BASE_URL}{config.path.format(path_value) if path_value else config.path}"

        while True:
            params: dict[str, Any] = {"page_size": PAGE_SIZE}
            if cursor_id:
                params[cursor_param] = cursor_id
            if start_datetime:
                params["start_datetime"] = start_datetime

            data = _fetch_page(session, url, params, logger)
            items = data.get(collection_key, [])
            if not items:
                break

            has_more = bool(data.get("has_more", False))

            reached_watermark = False
            rows: list[dict[str, Any]] = []
            for item in items:
                if last_value_dt is not None:
                    created = _parse_datetime(item.get(incremental_field_name))
                    if created is not None and created <= last_value_dt:
                        reached_watermark = True
                        break
                rows.append(item)

            if rows:
                yield _redact(rows, config.redacted_fields)
                # Save the cursor for the page we just yielded (not the next one) so a crash re-fetches
                # and re-yields this page — merge dedupes on the `id` primary key — rather than skipping it.
                if config.ascending:
                    resumable_source_manager.save_state(EasypostResumeConfig(after_id=cursor_id, path_value=path_value))
                else:
                    resumable_source_manager.save_state(
                        EasypostResumeConfig(before_id=cursor_id, path_value=path_value)
                    )

            if reached_watermark or not has_more:
                break

            cursor_id = items[-1]["id"]

        cursor_id = None


def easypost_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EasypostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = EASYPOST_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        # EasyPost list endpoints return records newest-first (descending creation time), except
        # the ones that page forward with `after_id`.
        sort_mode="asc" if config.ascending else "desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
