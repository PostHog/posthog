from datetime import UTC, datetime
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slash import SlashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PERMISSION_ERROR,
    REQUEST_ERROR,
)


@frozen
class SlashResumeConfig:
    cursor: str


def invoice_with_id(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "id": row["invoice"]["id"]}


def validate_credentials(config: SlashSourceConfig, schema_name: str | None) -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, schema_name or "accounts")
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=config.api_key, name="X-API-Key"),
        headers={"x-legal-entity": config.legal_entity_id} if config.legal_entity_id else {},
        paginator=SinglePagePaginator(),
        allow_redirects=False,
        request_timeout=(10, 60),
    )
    try:
        next(client.paginate(path, data_selector="items"), None)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status == 400:
            return False, REQUEST_ERROR
        raise
    return True, None


def slash_source(
    config: SlashSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SlashResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: datetime | str | None,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    params: dict[str, Any] = {}
    if endpoint == "transactions" and should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = db_incremental_field_last_value
        if isinstance(watermark, str):
            watermark = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
        if watermark.tzinfo is None:
            watermark = watermark.replace(tzinfo=UTC)
        params["filter:from_date"] = int(watermark.timestamp() * 1000)

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "items",
        "data_selector_required": True,
        "paginator": "single_page"
        if endpoint == "accounts"
        else {
            "type": "cursor",
            "cursor_path": "metadata.nextCursor",
            "cursor_param": "cursor",
            "raise_on_repeated_cursor": True,
        },
    }
    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    if endpoint == "invoices":
        resource_config["data_map"] = invoice_with_id

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "X-API-Key", "location": "header"},
            "headers": {"x-legal-entity": config.legal_entity_id} if config.legal_entity_id else {},
            "allow_redirects": False,
            "request_timeout": (10, 60),
        },
        "resources": [resource_config],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(SlashResumeConfig(cursor=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        # Slash does not document an ascending transaction order, so checkpoint only after the complete scan.
        sort_mode="desc",
        supports_resume=endpoint != "accounts",
    )
