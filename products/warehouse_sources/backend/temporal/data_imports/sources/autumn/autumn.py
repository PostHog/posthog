import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionMode,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import (
    AUTUMN_BASE_URL,
    AUTUMN_ENDPOINTS,
    PARTITION_BUCKET_MILLISECONDS,
    AutumnEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class AutumnResumeConfig:
    next_cursor: str


def _watermark_to_epoch_ms(value: Any) -> int:
    """Coerce the persisted incremental watermark to epoch milliseconds."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    return int(value)


def _make_paginator(config: AutumnEndpointConfig) -> BasePaginator:
    if config.paginated:
        return JSONResponseCursorPaginator(
            cursor_path="next_cursor",
            cursor_param="start_cursor",
            param_location="json",
        )
    return SinglePagePaginator()


def _build_request_body(
    config: AutumnEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    # Single-page endpoints document an optional (or absent) request body; an empty JSON
    # object is accepted either way and keeps the request shape uniform.
    body: dict[str, Any] = {}
    if config.paginated:
        body["limit"] = config.page_size
    if (
        config.incremental_range_field is not None
        and should_use_incremental_field
        and incremental_field == config.incremental_range_field
        and db_incremental_field_last_value is not None
    ):
        # The docs don't state whether custom_range.start is inclusive; starting exactly at
        # the watermark may re-fetch boundary rows, which the merge on primary key dedupes.
        body["custom_range"] = {"start": _watermark_to_epoch_ms(db_incremental_field_last_value)}
    return body


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    json_body: dict[str, Any],
) -> EndpointResource:
    config = AUTUMN_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "method": "POST",
        "path": config.path,
        "json": json_body,
        "data_selector": config.data_selector,
        "paginator": _make_paginator(config),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def autumn_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[AutumnResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = AUTUMN_ENDPOINTS[endpoint]

    json_body = _build_request_body(
        config,
        should_use_incremental_field,
        incremental_field,
        db_incremental_field_last_value,
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": AUTUMN_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {"x-api-version": api_version},
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, json_body)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(AutumnResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering rides the custom_range body param above, not the
        # framework's query-param incremental machinery.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    partition_size: Optional[int] = None
    if config.partition_key is not None:
        partition_keys = [config.partition_key]
        partition_mode = "numerical"
        partition_size = PARTITION_BUCKET_MILLISECONDS

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_size=partition_size,
        # The docs don't state list ordering; usage-event logs are typically newest-first,
        # and "desc" is also the safe choice if the order turns out to be ascending — the
        # watermark then only commits once the sync completes.
        sort_mode="desc" if config.incremental_range_field is not None else "asc",
    )


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,))
    response = session.post(
        f"{AUTUMN_BASE_URL}/v1/customers.list",
        headers={
            "Authorization": f"Bearer {api_key}",
            "x-api-version": api_version,
        },
        json={"limit": 1},
        timeout=30,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, (
            "Autumn rejected the secret key. Check that you copied a secret key (am_sk_...) "
            "for the environment you want to sync."
        )
    return False, f"Autumn returned an unexpected status ({response.status_code})"
