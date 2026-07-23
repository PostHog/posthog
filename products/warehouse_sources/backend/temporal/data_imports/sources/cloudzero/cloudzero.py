import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from dateutil import parser as dateutil_parser

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.settings import (
    DEFAULT_START_DATE,
    RESTATEMENT_WINDOW_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLOUDZERO_BASE_URL = "https://api.cloudzero.com"


@dataclasses.dataclass
class CloudzeroResumeConfig:
    next_cursor: str


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return dateutil_parser.parse(str(value))


def _format_iso8601(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _rolling_incremental_start_date(value: Any) -> str:
    """Roll the incremental `start_date` back a few days to recapture CloudZero cost restatements."""
    dt = _to_datetime(value) - timedelta(days=RESTATEMENT_WINDOW_DAYS)
    return _format_iso8601(dt)


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    granularity: str,
    cost_type: str,
    group_by: list[str],
) -> EndpointResource:
    if name == "Dimensions":
        return {
            "name": "Dimensions",
            "table_name": "dimensions",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "dimensions",
                "path": "/v2/billing/dimensions",
                "params": {
                    "include_hidden": "true",
                },
                "data_selector_required": True,
            },
            "table_format": "delta",
        }

    params: dict[str, Any] = {
        "start_date": (
            {
                "type": "incremental",
                "cursor_path": "usage_date",
                "initial_value": DEFAULT_START_DATE,
                "convert": _rolling_incremental_start_date,
            }
            if should_use_incremental_field
            else DEFAULT_START_DATE
        ),
        "granularity": granularity,
        "cost_type": cost_type,
    }
    if group_by:
        # CloudZero accepts `group_by` as a repeated query param (one per dimension id).
        params["group_by"] = group_by

    return {
        "name": "Costs",
        "table_name": "costs",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        },
        "endpoint": {
            "data_selector": "costs",
            "path": "/v2/billing/costs",
            "params": params,
            "data_selector_required": True,
            "paginator": {
                "type": "cursor",
                "cursor_path": "pagination.cursor.next_cursor",
                "cursor_param": "cursor",
                "param_location": "query",
            },
        },
        "table_format": "delta",
    }


def cloudzero_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudzeroResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    granularity: str = "daily",
    cost_type: str = "real_cost",
    group_by: Optional[list[str]] = None,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": CLOUDZERO_BASE_URL,
            "auth": {
                # CloudZero puts the raw API key in `Authorization` — no `Bearer` prefix.
                "type": "api_key",
                "name": "Authorization",
                "api_key": api_key,
                "location": "header",
            },
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            },
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, granularity, cost_type, group_by or [])],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the manager's TTL (24h) already
        # matches CloudZero's own cursor validity window, so an expired resume naturally falls
        # back to a fresh query rather than replaying a stale (410 Expired Cache) cursor.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(CloudzeroResumeConfig(next_cursor=str(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> bool:
    res = make_tracked_session(redact_values=(api_key,)).get(
        f"{CLOUDZERO_BASE_URL}/v2/billing/dimensions",
        headers={"Authorization": api_key},
    )
    return res.status_code == 200
