import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import EASYPOST_ENDPOINTS

EASYPOST_BASE_URL = "https://api.easypost.com/v2"
# EasyPost caps page_size at 100 across cursor-paginated list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class EasypostRetryableError(Exception):
    pass


@dataclasses.dataclass
class EasypostResumeConfig:
    # `before_id` of the page we last yielded. EasyPost paginates newest-first, so advancing the
    # cursor means asking for records created *before* this id. `None` resumes from the first page.
    before_id: str | None = None


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


@retry(
    retry=retry_if_exception_type((EasypostRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger
) -> dict[str, Any]:
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

    session = make_tracked_session(redact_values=(api_key,))
    session.auth = (api_key, "")

    # Incremental cursor: EasyPost returns newest-first, so we walk backwards (via `before_id`) and
    # stop once a page reaches the watermark. `start_datetime` filters server-side on `created_at`
    # as an optimization; the client-side stop guarantees correct, bounded behaviour even if the
    # endpoint ignores the filter when combined with cursor pagination.
    last_value_dt: datetime | None = None
    start_datetime: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        last_value_dt = _parse_datetime(db_incremental_field_last_value)
        if last_value_dt is not None:
            start_datetime = _format_datetime(last_value_dt)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    before_id = resume.before_id if resume else None
    if before_id:
        logger.debug(f"EasyPost: resuming {endpoint} from before_id={before_id}")

    while True:
        params: dict[str, Any] = {"page_size": PAGE_SIZE}
        if before_id:
            params["before_id"] = before_id
        if start_datetime:
            params["start_datetime"] = start_datetime

        data = _fetch_page(session, f"{EASYPOST_BASE_URL}{config.path}", params, logger)
        items = data.get(config.name, [])
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
            yield rows
            # Save the cursor for the page we just yielded (not the next one) so a crash re-fetches
            # and re-yields this page — merge dedupes on the `id` primary key — rather than skipping it.
            resumable_source_manager.save_state(EasypostResumeConfig(before_id=before_id))

        if reached_watermark or not has_more:
            break

        before_id = items[-1]["id"]


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
        # EasyPost list endpoints return records newest-first (descending creation time).
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
