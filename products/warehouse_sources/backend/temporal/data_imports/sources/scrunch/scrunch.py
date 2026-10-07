from datetime import UTC, datetime
from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.settings import (
    BASE_URL,
    ENDPOINTS,
    NON_RETRYABLE_ERRORS,
    PAGE_SIZE,
    PRIMARY_KEYS,
)


@frozen
class ScrunchResumeConfig:
    paginator_state: dict[str, Any] | None
    start_date: str | None
    end_date: str | None
    complete: bool = False


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(base_url=BASE_URL, auth=BearerTokenAuth(api_key), request_timeout=60)
    try:
        next(
            client.paginate(
                "brands",
                params={"limit": 1},
                paginator=SinglePagePaginator(),
                data_selector="items",
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        for pattern, message in NON_RETRYABLE_ERRORS.items():
            if pattern in str(error):
                return False, message
        raise
    return True, None


def scrunch_source(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ScrunchResumeConfig],
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, inputs.schema_name)
    is_responses = inputs.schema_name == "responses"
    resume = manager.load_state() if manager.can_resume() else None
    start_date = None
    # Exclude the open UTC day so new responses cannot move offsets during a sync.
    end_date = datetime.now(UTC).date().isoformat() if is_responses else None
    if resume is not None:
        start_date, end_date = resume.start_date, resume.end_date
    elif is_responses and inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
        if watermark is None:
            raise ValueError("Invalid Scrunch response watermark. Reset this table's sync.")
        # Date filters include the whole watermark day; merging prevents duplicate rows.
        start_date = watermark.date().isoformat()

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(
            ScrunchResumeConfig(
                paginator_state=state,
                start_date=start_date,
                end_date=end_date,
                complete=state is None,
            )
        )

    parent: EndpointResource = {"name": "brands", "endpoint": {"path": ENDPOINTS["brands"]}}
    resources: list[EndpointResource] = [parent]
    if inputs.schema_name != "brands":
        params: dict[str, Any] = {"brand_id": {"type": "resolve", "resource": "brands", "field": "id"}}
        if inputs.schema_name == "prompts":
            params["status"] = "all"
        if is_responses:
            params["end_date"] = end_date
            if start_date is not None:
                params["start_date"] = start_date
        resources.append(
            {
                "name": inputs.schema_name,
                "include_from_parent": ["id"],
                "endpoint": {"path": path, "params": params},
                "data_map": rename_parent_fields("brands", {"id": "brand_id"}),
            }
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": "total"},
            "request_timeout": 60,
        },
        "resource_defaults": {"endpoint": {"data_selector": "items", "data_selector_required": True}},
        "resources": resources,
    }
    resource = next(
        resource
        for resource in rest_api_resources(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
        if resource.name == inputs.schema_name
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=(lambda: []) if resume and resume.complete else (lambda: resource),
        primary_keys=PRIMARY_KEYS[inputs.schema_name],
        sort_mode="desc" if is_responses else None,
        partition_keys=["created_at"] if is_responses else None,
        partition_mode="datetime" if is_responses else None,
        partition_format="month" if is_responses else None,
    )
