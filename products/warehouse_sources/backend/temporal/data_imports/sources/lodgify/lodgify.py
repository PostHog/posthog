from datetime import datetime
from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PATHS,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)


@frozen
class LodgifyResumeConfig:
    paginator_state: dict[str, Any]


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        BASE_URL,
        auth=APIKeyAuth(api_key, name="X-ApiKey"),
        headers={"Accept": "application/json"},
        request_timeout=(10, 60),
    )
    try:
        next(
            client.paginate(
                path="properties",
                params={"page": 1, "size": 1},
                paginator=SinglePagePaginator(),
                data_selector="items",
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return False, AUTH_ERROR if error.response.status_code == 401 else PERMISSION_ERROR
        raise
    return True, None


def list_resource(endpoint: str, watermark: datetime | str | None = None) -> EndpointResource:
    params: dict[str, Any] = {"size": PAGE_SIZE}
    if endpoint == "bookings":
        params.update(stayFilter="All", trash="All", includeTransactions="true", includeQuoteDetails="true")
    if watermark is not None:
        parsed = parse_datetime_value(watermark)
        if parsed is None:
            raise ValueError("Invalid Lodgify sync timestamp. Reset the table and try again.")
        params["updatedSince"] = parsed.isoformat()
    endpoint_config: Endpoint = {
        "path": PATHS[endpoint],
        "params": params,
        "data_selector": "items",
        "data_selector_required": True,
        "paginator": PageNumberPaginator(base_page=1),
    }
    return {
        "name": endpoint,
        "endpoint": endpoint_config,
        "columns": {"created_at": {"data_type": "timestamp"}, "updated_at": {"data_type": "timestamp"}},
    }


def lodgify_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LodgifyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: datetime | str | None = None,
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unsupported Lodgify table: {endpoint}")

    initial_state = None
    if resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None:
            initial_state = saved.paginator_state

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(LodgifyResumeConfig(paginator_state=state))

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "X-ApiKey", "api_key": api_key, "location": "header"},
            "headers": {"Accept": "application/json"},
            "request_timeout": (10, 60),
        },
        "resources": [],
    }
    if endpoint == "rooms":
        config["resources"] = [
            list_resource("properties"),
            {
                "name": "rooms",
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": PATHS["rooms"],
                    "params": {"id": {"type": "resolve", "resource": "properties", "field": "id"}},
                    "paginator": "single_page",
                    "data_selector": "$",
                    "data_selector_required": True,
                },
            },
        ]
        resources = rest_api_resources(
            config, team_id, job_id, None, resume_hook=save_checkpoint, initial_paginator_state=initial_state
        )
        resource = next(resource for resource in resources if resource.name == "rooms")
        resource.add_map(rename_parent_fields("properties", {"id": "property_id"}))
    else:
        watermark = db_incremental_field_last_value if should_use_incremental_field else None
        config["resources"] = [list_resource(endpoint, watermark)]
        resource = rest_api_resource(
            config, team_id, job_id, None, resume_hook=save_checkpoint, initial_paginator_state=initial_state
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        column_hints=resource.column_hints,
        # The API does not guarantee ascending update order; save the watermark after the complete scan.
        sort_mode="desc",
    )
