import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.settings import (
    CORE_ENDPOINT_PATHS,
    DEFAULT_METRICS_LOOKBACK_DAYS,
    INCREMENTAL_FIELDS,
    MAX_PAGE_SIZE,
    METRIC_ENDPOINT_PATHS,
    METRIC_ENDPOINTS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    TABLE_NAMES,
)

# Shared host for the Metrics API (Coding metrics, Collaboration/PR metrics) — unlike the Customer
# API, it is not workspace-specific. Flow moved this off `flow-api.pluralsight.com` to
# `api.appfireflow.com` on 2025-07-23; the old host is no longer guaranteed to work.
METRICS_BASE_URL = "https://api.appfireflow.com"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots), so the stored API key is only ever sent to `<workspace>.appfireflow.com`.
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


@frozen
class PluralsightFlowResumeConfig:
    offset: int


def normalize_workspace(workspace: str) -> str:
    """Reduce user input to a bare, validated Flow workspace label.

    Accepts either the full host (``acme.appfireflow.com``) or the bare workspace (``acme``).
    Raises ``ValueError`` on anything that isn't a single DNS label, so the API key can never be
    sent to a host the user doesn't control.
    """
    cleaned = workspace.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".appfireflow.com")
    if not _WORKSPACE_RE.match(cleaned):
        raise ValueError(
            f"Invalid Flow workspace: {workspace!r}. Enter just the workspace, e.g. 'acme' for acme.appfireflow.com."
        )
    return cleaned


def _core_base_url(workspace: str) -> str:
    return f"https://{normalize_workspace(workspace)}.appfireflow.com/v3/customer/core"


def _format_incremental_value(value: Any) -> str:
    """Format a date/datetime-like value as the naive ISO datetime Flow's `__gte`/`__lt`
    filters document (e.g. `2018-06-25T00:00:00`). Falls back to `str(value)` for values that
    are already a formatted string (e.g. our own `initial_value` seed)."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S")


def _core_client_config(workspace: str, api_key: str) -> ClientConfig:
    return {
        "base_url": _core_base_url(workspace),
        "auth": {"type": "bearer", "token": api_key},
        # Flow returns a page shorter than `limit` once exhausted; `total_path` gives an extra,
        # cheaper stop signal from the response envelope's documented `count` field.
        "paginator": OffsetPaginator(limit=MAX_PAGE_SIZE, total_path="count", stop_after_empty_page=True),
    }


def _core_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    incremental_fields = INCREMENTAL_FIELDS.get(name)
    params: dict[str, Any] = {}
    is_incremental = bool(incremental_fields) and should_use_incremental_field
    if incremental_fields and is_incremental:
        field = incremental_fields[0]["field"]
        params[f"{field}__gte"] = {
            "type": "incremental",
            "cursor_path": field,
            "initial_value": "1970-01-01T00:00:00",
            "convert": _format_incremental_value,
        }

    return {
        "name": name,
        "table_name": TABLE_NAMES[name],
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {
            "path": CORE_ENDPOINT_PATHS[name],
            "params": params,
            # Flow's Customer API wraps list responses as `{count, next, previous, results}`.
            "data_selector": "results",
        },
        "table_format": "delta",
    }


def _default_metrics_date_range(today: Optional[date] = None) -> str:
    end = today or datetime.now(UTC).date()
    start = end - timedelta(days=DEFAULT_METRICS_LOOKBACK_DAYS)
    return f"[{start.isoformat()}:{end.isoformat()}]"


def _stamp_date_range(date_range: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "date_range": date_range}

    return _map


def _metrics_resource(name: str, date_range: str) -> EndpointResource:
    return {
        "name": name,
        "table_name": TABLE_NAMES[name],
        "write_disposition": "replace",
        "endpoint": {
            "path": METRIC_ENDPOINT_PATHS[name],
            "params": {"date_range": date_range},
            # The metrics endpoints return one aggregate JSON object, not a list.
            "data_selector": "$",
            "paginator": SinglePagePaginator(),
        },
        "data_map": _stamp_date_range(date_range),
    }


def pluralsight_flow_source(
    api_key: str,
    workspace: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PluralsightFlowResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    if endpoint in METRIC_ENDPOINTS:
        metrics_config: RESTAPIConfig = {
            "client": {"base_url": METRICS_BASE_URL, "auth": {"type": "bearer", "token": api_key}},
            "resource_defaults": {},
            "resources": [_metrics_resource(endpoint, _default_metrics_date_range())],
        }
        resource = rest_api_resource(metrics_config, team_id, job_id, None)
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS[endpoint],
            column_hints=resource.column_hints,
        )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and "offset" in state:
            resumable_source_manager.save_state(PluralsightFlowResumeConfig(offset=int(state["offset"])))

    core_config: RESTAPIConfig = {
        "client": _core_client_config(workspace, api_key),
        "resource_defaults": {},
        "resources": [_core_resource(endpoint, should_use_incremental_field)],
    }

    resource = rest_api_resource(
        core_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    partition_field = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        column_hints=resource.column_hints,
        partition_mode="datetime" if partition_field else None,
        partition_keys=[partition_field] if partition_field else None,
    )


def validate_credentials(api_key: str, workspace: str) -> tuple[bool, int | None]:
    url = f"{_core_base_url(workspace)}/users/?limit=1"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
