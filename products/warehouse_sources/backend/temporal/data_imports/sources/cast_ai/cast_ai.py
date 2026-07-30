import dataclasses
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.settings import (
    CASTAI_BASE_URL,
    CASTAI_ENDPOINTS,
    COST_REPORT_STEP_SECONDS,
    DEFAULT_LOOKBACK_DAYS,
    CastAiEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class CastAiResumeConfig:
    # Opaque framework checkpoint (fan-out resume state for the two report endpoints; the
    # "clusters" list has no pagination and is never resumed).
    paginator_state: dict[str, Any]


def _format_time_value(value: Any) -> str:
    """Format an incremental watermark, or our own default lookback, as RFC 3339 UTC."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_lookback_start() -> str:
    return _format_time_value(datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS))


def _now() -> str:
    return _format_time_value(datetime.now(UTC))


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": CASTAI_BASE_URL,
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
        "headers": {"Accept": "application/json"},
        # X-API-Key is a custom header requests keeps across origins, so never follow a
        # redirect that could hand the CAST AI key to another host.
        "allow_redirects": False,
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # ListClusters is the cheapest authenticated call available (no required params, and an
    # empty cluster list is still a valid 200), so it doubles as the credential probe.
    res = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
        f"{CASTAI_BASE_URL}/v1/kubernetes/external-clusters",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
        timeout=10,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code in (401, 403):
        return False, "Invalid or unauthorized CAST AI API key"
    return False, f"CAST AI API returned an unexpected status: {res.status_code}"


def get_resource(endpoint: str) -> EndpointResource:
    config = CASTAI_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "items",
        "paginator": SinglePagePaginator(),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _report_incremental_config_factory(start_param: str, end_param: str) -> Any:
    end_value = _now()

    def factory(field: str) -> IncrementalConfig:
        return {
            "cursor_path": field,
            "start_param": start_param,
            "end_param": end_param,
            "initial_value": _default_lookback_start(),
            "end_value": end_value,
            "convert": _format_time_value,
        }

    return factory


def _make_source_response(endpoint_config: CastAiEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def cast_ai_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CastAiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = CASTAI_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's somewhere to resume to; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(CastAiResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout:
        start_param, end_param = (
            ("startTime", "endTime") if endpoint == "cluster_cost_reports" else ("fromDate", "toDate")
        )
        # These reports require a time window on every request (full refresh included) so the
        # literal defaults below are always present; when incremental sync is enabled the
        # framework's incremental config overwrites them with the real last-synced watermark.
        child_params_extra: dict[str, Any] = {
            start_param: _default_lookback_start(),
            end_param: _now(),
        }
        if endpoint == "cluster_cost_reports":
            child_params_extra["stepSeconds"] = COST_REPORT_STEP_SECONDS

        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=CASTAI_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_report_incremental_config_factory(start_param, end_param),
                page_size_param=None,
                parent_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": "items"},
                child_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": "items"},
                child_params_extra=child_params_extra,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint=endpoint)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
