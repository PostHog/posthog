import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.settings import (
    OURA_ENDPOINTS,
    OuraEndpointConfig,
)

OURA_BASE_URL = "https://api.ouraring.com/v2"

# Oura rings didn't exist before 2015; this lower bound guarantees a full backfill on first sync.
# The API defaults start_date to end_date - 1 day, so an explicit early start is required to pull
# history rather than just the most recent day.
DEFAULT_START_DATE = "2014-01-01"
DEFAULT_START_DATETIME = f"{DEFAULT_START_DATE}T00:00:00+00:00"

VALIDATE_TIMEOUT_SECONDS = 10


@dataclasses.dataclass
class OuraResumeConfig:
    # Opaque pagination cursor returned by the API as `next_token`. Resuming re-issues the same
    # date-windowed request with this token appended.
    next_token: str | None = None


def _format_date(value: Any) -> str:
    """Format a date cursor value as the YYYY-MM-DD string Oura's start_date expects."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Stored cursor can come back as an ISO string; the date component is the first 10 chars.
    return str(value)[:10]


def _format_datetime(value: Any) -> str:
    """Format a datetime cursor value as the ISO 8601 string Oura's start_datetime expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _clamp_date_to_today(value: str) -> str:
    """Cap a start_date at today. A future-dated record can push the cursor past today, and Oura
    400s when start_date is after end_date (which defaults to today)."""
    today = datetime.now(UTC).date().isoformat()
    return today if value > today else value


def _clamp_datetime_to_now(value: str) -> str:
    now = datetime.now(UTC).isoformat()
    return now if value > now else value


def _start_date_param(value: Any) -> str:
    return _clamp_date_to_today(_format_date(value))


def _start_datetime_param(value: Any) -> str:
    return _clamp_datetime_to_now(_format_datetime(value))


def probe_endpoint(token: str, path: str) -> int:
    """Return the HTTP status code for a minimal GET against `path`. -1 on a transport failure."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(token,)),
        f"{OURA_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=VALIDATE_TIMEOUT_SECONDS,
    )
    return status if status is not None else -1


def _build_endpoint_config(config: OuraEndpointConfig) -> Endpoint:
    if config.is_single_document:
        # Single-document endpoints (e.g. personal_info) return a flat object, not a
        # {data: [...], next_token} envelope. With no data_selector the whole body is emitted as
        # a single row.
        return {"path": config.path, "paginator": SinglePagePaginator()}

    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": "data",
        # A 200 body without `data` means the response shape changed — fail loud instead of
        # silently syncing 0 rows.
        "data_selector_required": True,
        "paginator": JSONResponseCursorPaginator(cursor_path="next_token", cursor_param="next_token"),
    }

    # A server-side date window is always sent (even on full refresh) so the first sync backfills
    # history from DEFAULT_START_DATE rather than just the most recent day; the checkpointed
    # watermark advances it on subsequent runs.
    if config.date_filter == "date":
        endpoint["incremental"] = {
            "start_param": "start_date",
            "initial_value": DEFAULT_START_DATE,
            "convert": _start_date_param,
        }
    elif config.date_filter == "datetime":
        endpoint["incremental"] = {
            "start_param": "start_datetime",
            "initial_value": DEFAULT_START_DATETIME,
            "convert": _start_datetime_param,
        }

    return endpoint


def oura_source(
    token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OuraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OURA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": OURA_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": token},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint_config(config),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_token:
            initial_paginator_state = {"cursor": resume.next_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(OuraResumeConfig(next_token=str(state["cursor"])))

    # Gate the incremental cursor on the sync mode: on full refresh the framework falls back to the
    # endpoint's initial_value (DEFAULT_START_(DATE|DATETIME)).
    incremental_last_value = db_incremental_field_last_value if should_use_incremental_field else None

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        incremental_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Oura returns records in ascending date order; we additionally re-window by start_date on
        # every sync, so the checkpointed watermark advances correctly.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
