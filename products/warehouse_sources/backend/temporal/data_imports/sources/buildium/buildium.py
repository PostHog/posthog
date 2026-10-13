from datetime import UTC, datetime
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)


@frozen
class BuildiumResumeConfig:
    offset: int
    updated_from: str | None = None


def validate_credentials(config: BuildiumSourceConfig, endpoint: str, api_version: str) -> None:
    path = schema_for_resource(ENDPOINTS, endpoint)
    with make_tracked_session(redact_values=(config.client_secret,)) as session:
        response = session.get(
            f"{BASE_URL}/{api_version}/{path}",
            headers={"x-buildium-client-id": config.client_id},
            auth=APIKeyAuth(config.client_secret, name="x-buildium-client-secret"),
            params={"limit": 1},
            timeout=(10, 30),
        )
        response.raise_for_status()


def buildium_source(
    config: BuildiumSourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuildiumResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: datetime | str | None,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    incremental = should_use_incremental_field and endpoint in INCREMENTAL_FIELDS
    updated_from = None
    if incremental and db_incremental_field_last_value is not None:
        watermark = db_incremental_field_last_value
        if isinstance(watermark, str):
            watermark = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
        if watermark.tzinfo is None:
            watermark = watermark.replace(tzinfo=UTC)
        updated_from = watermark.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        # Keep the original filter because changing it would shift the saved offset.
        updated_from = resume.updated_from

    # Keep offset pagination stable when an object is updated during extraction. Ordering by the
    # mutable update timestamp can move an already-read object to a later page and skip another one.
    params: dict[str, Any] = {"orderby": "Id asc"}
    if updated_from is not None:
        params["lastupdatedfrom"] = updated_from

    endpoint_config: Endpoint = {"path": path, "data_selector": "$", "params": params}
    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": endpoint_config,
        "columns": {"LastUpdatedDateTime": {"data_type": "timestamp"}} if endpoint in INCREMENTAL_FIELDS else {},
    }
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/",
            "request_timeout": (10, 30),
            "headers": {"x-buildium-client-id": config.client_id},
            "auth": {"type": "api_key", "name": "x-buildium-client-secret", "api_key": config.client_secret},
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None, "total_header": "X-Total-Count"},
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                BuildiumResumeConfig(offset=int(state["offset"]), updated_from=updated_from)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": resume.offset} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["Id"],
        column_hints=resource.column_hints,
        # Incremental rows are ID-ordered rather than timestamp-ordered, so only advance the
        # timestamp watermark after a complete extraction.
        sort_mode="desc",
    )
