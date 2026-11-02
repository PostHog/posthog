import dataclasses
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any, Optional

from dateutil import parser

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.settings import (
    PAGE_LIMIT,
    ZYLO_BASE_URL,
    ZYLO_ENDPOINTS,
    ZyloEndpointConfig,
)

# Far-past cutoff used on the first incremental sync (no stored watermark yet) so we pull the
# full history before the cursor takes over on subsequent runs.
INITIAL_INCREMENTAL_VALUE = "1970-01-01"


@dataclasses.dataclass(frozen=True)
class ZyloResumeConfig:
    next_skip: Optional[int] = None
    # AutomationExecutions fans out over Automations, so its resume state is the shape
    # `build_dependent_resource` checkpoints: finished parents and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _format_zylo_filter_date(value: Any) -> str:
    """Format an incremental cursor value as the `<value>,gte` filter Zylo expects.

    Zylo's documented filter syntax (https://developer.zylo.com/reference/filtering) only shows
    date-granularity (`YYYY-MM-DD`) values, even for datetime fields like `zylo_created_at` —
    there is no documented full-timestamp filter format, so we truncate to the day. Incremental
    merge-upsert on `id` de-dupes any same-day rows re-fetched across runs.
    """
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        try:
            d = parser.parse(str(value)).date()
        except (ValueError, OverflowError):
            return f"{value},gte"
    return f"{d.isoformat()},gte"


def _resolve_cursor(
    config: ZyloEndpointConfig, should_use_incremental_field: bool, incremental_field: Optional[str]
) -> Optional[str]:
    if not (should_use_incremental_field and config.incremental_fields):
        return None
    # Honor the user's chosen cursor field; fall back to the first advertised option.
    advertised = {f["field"] for f in config.incremental_fields}
    return incremental_field if incremental_field in advertised else config.incremental_fields[0]["field"]


def _incremental_config(cursor: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor,
        "start_param": cursor,
        "initial_value": INITIAL_INCREMENTAL_VALUE,
        "convert": _format_zylo_filter_date,
    }


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> EndpointResource:
    config: ZyloEndpointConfig = ZYLO_ENDPOINTS[endpoint]

    cursor = _resolve_cursor(config, should_use_incremental_field, incremental_field)
    is_incremental = cursor is not None

    sort_field = cursor or "zylo_created_at"
    params: dict[str, Any] = {
        "sort": f"+{sort_field}",
    }
    if cursor is not None:
        params[cursor] = {
            "type": "incremental",
            "cursor_path": cursor,
            "initial_value": INITIAL_INCREMENTAL_VALUE,
            "convert": _format_zylo_filter_date,
        }

    endpoint_def: Endpoint = {
        "path": config.path,
        "params": params,
    }

    return {
        "name": config.name,
        "table_name": config.table_name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint_def,
        "table_format": "delta",
    }


def zylo_source(
    token_id: str,
    token_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZyloResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = ZYLO_ENDPOINTS[endpoint]
    client_config: ClientConfig = {
        "base_url": ZYLO_BASE_URL,
        "auth": {
            "type": "bearer",
            "token": f"{token_id}:{token_secret}",
        },
        "paginator": OffsetPaginator(
            limit=PAGE_LIMIT,
            offset_param="skip",
            limit_param="limit",
            total_path=None,
        ),
    }

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint_config.fanout is not None:
        cursor = _resolve_cursor(endpoint_config, should_use_incremental_field, incremental_field)

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(ZyloResumeConfig(fanout_state=state))

        child = build_dependent_resource(
            endpoint_configs=ZYLO_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=cursor,
            incremental_config_factory=_incremental_config,
            child_params_extra={"sort": f"+{cursor or 'zylo_created_at'}"},
            # The client's OffsetPaginator already sends `limit`.
            page_size_param=None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume_config.fanout_state if resume_config else None,
        )
        return _make_source_response(endpoint_config, lambda: child)

    config: RESTAPIConfig = {
        "client": client_config,
        # Write disposition is set per-resource in get_resource (it always wins over
        # resource_defaults), so no default is needed here.
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume_config is not None and resume_config.next_skip is not None:
        initial_paginator_state = {"offset": resume_config.next_skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to. Redis TTL handles cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ZyloResumeConfig(next_skip=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(endpoint_config, lambda: resource)


def _make_source_response(endpoint_config: ZyloEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(token_id: str, token_secret: str) -> bool:
    try:
        response = make_tracked_session(redact_values=(token_secret,)).get(
            f"{ZYLO_BASE_URL}/v2/applications",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token_id}:{token_secret}"},
            timeout=30,
        )
    except Exception:
        return False
    return response.status_code == 200


def probe_endpoint_status(token_id: str, token_secret: str, path: str) -> Optional[int]:
    """Probe a single endpoint with the cheapest possible request; returns the HTTP status,
    or ``None`` when the request itself failed (network blip — not a permission signal)."""
    try:
        response = make_tracked_session(redact_values=(token_secret,)).get(
            f"{ZYLO_BASE_URL}{path}",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token_id}:{token_secret}"},
            timeout=30,
        )
    except Exception:
        return None
    return response.status_code
