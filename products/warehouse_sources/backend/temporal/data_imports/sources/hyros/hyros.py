from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.settings import HYROS_ENDPOINTS, PAGE_SIZE

BASE_URL = "https://api.hyros.com/v1"


@frozen
class HyrosResumeConfig:
    cursor: str


def _format_hyros_date(value: Any) -> Optional[str]:
    """Format an incremental cursor as the ISO 8601, offset-aware date Hyros' `fromDate` /
    `updatedFromDate` filters expect. `None` passes through so the pipeline drops the param
    from the request instead of sending a literal "None"."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.isoformat(timespec="seconds")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat(timespec="seconds")
    return str(value)


def _resource_for(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    config = HYROS_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and config.incremental_query_param is not None

    params: dict[str, Any] = {"pageSize": PAGE_SIZE}
    if config.incremental_query_param is not None:
        params[config.incremental_query_param] = (
            {
                "type": "incremental",
                "cursor_path": config.incremental_field_name,
                "initial_value": None,
                "convert": _format_hyros_date,
            }
            if should_use_incremental_field
            else None
        )

    return {
        "name": endpoint,
        "table_name": endpoint.lower(),
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {
            "data_selector": "result",
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "api_key": api_key, "name": "API-Key", "location": "header"},
        # A validated host could 3xx to an attacker-controlled host without stripping the
        # `API-Key` header; refuse to follow redirects (SSRF/credential-leak guard).
        "allow_redirects": False,
        # Every list endpoint shares the same `{result, nextPageId, request_id}` envelope.
        "paginator": JSONResponseCursorPaginator(cursor_path="nextPageId", cursor_param="pageId"),
    }


def hyros_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HyrosResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = HYROS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [_resource_for(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(HyrosResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    has_partition = config.partition_key is not None
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1 if has_partition else None,
        partition_size=1 if has_partition else None,
        partition_mode="datetime" if has_partition else None,
        partition_format="month" if has_partition else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Hyros doesn't document the order `pageId` cursoring returns rows in. Ascending is the
        # conservative default the framework and every other cursor-paginated source here assume;
        # flag it explicitly since it's unverified rather than confirmed against the live API.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe Hyros' `/user-info` endpoint to confirm the API key is genuine."""
    url = f"{BASE_URL}/api/v1.0/user-info"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"API-Key": api_key},
        # API-Key rides a custom header requests won't strip on a cross-origin redirect.
        allow_redirects=False,
    )
