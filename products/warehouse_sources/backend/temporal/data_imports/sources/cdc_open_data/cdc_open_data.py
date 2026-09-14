import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.settings import (
    CDC_BASE_URL,
    PAGE_SIZE,
    SOCRATA_ID_FIELD,
    SOCRATA_UPDATED_AT_FIELD,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import AuthConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

APP_TOKEN_HEADER = "X-App-Token"


@dataclasses.dataclass(frozen=False)
class CdcOpenDataResumeConfig:
    next_offset: int


def _format_where_value(value: Any) -> str:
    """Format an incremental cursor value for a Socrata `$where` timestamp comparison."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return str(value)


def _auth_config(app_token: str) -> Optional[AuthConfig]:
    if not app_token:
        return None
    return {"type": "api_key", "api_key": app_token, "name": APP_TOKEN_HEADER, "location": "header"}


def _probe_url(dataset_id: str) -> str:
    return f"{CDC_BASE_URL}/resource/{dataset_id}.json?{urlencode({'$limit': 1})}"


def cdc_open_data_source(
    dataset_id: str,
    app_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CdcOpenDataResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    params: dict[str, Any] = {
        # Every dataset's own columns vary, but every dataset carries these Socrata system
        # fields; requesting them explicitly (rather than relying on a version-specific
        # `$select`) works across SODA 2.0/2.1 alike.
        "$$exclude_system_fields": "false",
        "$order": f"{SOCRATA_UPDATED_AT_FIELD},{SOCRATA_ID_FIELD}"
        if should_use_incremental_field
        else SOCRATA_ID_FIELD,
    }
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        formatted_value = _format_where_value(db_incremental_field_last_value)
        params["$where"] = f"{SOCRATA_UPDATED_AT_FIELD} > '{formatted_value}'"

    paginator = OffsetPaginator(
        limit=PAGE_SIZE,
        offset_param="$offset",
        limit_param="$limit",
        total_path=None,
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        offset = state.get("offset") if state else None
        if offset is not None:
            resumable_source_manager.save_state(CdcOpenDataResumeConfig(next_offset=int(offset)))

    client: ClientConfig = {
        "base_url": CDC_BASE_URL,
        "paginator": paginator,
    }
    auth = _auth_config(app_token)
    if auth is not None:
        client["auth"] = auth

    resource_config: EndpointResource = {
        "name": dataset_id,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": f"/resource/{dataset_id}.json",
            "params": params,
            # A dataset endpoint always returns a bare JSON array; a non-list body means a
            # transient/error payload rather than zero rows.
            "data_selector_required": True,
        },
        "table_format": "delta",
    }
    config: RESTAPIConfig = {
        "client": client,
        "resources": [resource_config],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=dataset_id,
        items=lambda: resource,
        primary_keys=[SOCRATA_ID_FIELD],
        column_hints=resource.column_hints,
        sort_mode="asc",
    )


def validate_cdc_open_data_credentials(app_token: str, dataset_id: str) -> tuple[bool, str | None]:
    """Probe one dataset's resource endpoint to confirm it exists and the app token (if any) is valid."""
    headers = {APP_TOKEN_HEADER: app_token} if app_token else None
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(app_token,) if app_token else ()),
        _probe_url(dataset_id),
        headers=headers,
    )
    if ok:
        return True, None
    if status == 404:
        return (
            False,
            f"Dataset '{dataset_id}' was not found on data.cdc.gov. Check the dataset ID in its data.cdc.gov URL.",
        )
    if status == 403:
        return (
            False,
            "Invalid CDC Open Data app token. Check the token, or leave it blank to use the shared public pool.",
        )
    if status is None:
        return False, "Could not reach data.cdc.gov. Check your network connection and try again."
    return False, f"data.cdc.gov returned HTTP {status} for dataset '{dataset_id}'."
