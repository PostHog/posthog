from datetime import UTC, datetime
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginatorConfig,
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
    PRIMARY_KEYS,
    REQUEST_ERROR,
)

CURSOR_PAGINATOR: JSONResponseCursorPaginatorConfig = {
    "type": "cursor",
    "cursor_path": "metadata.nextCursor",
    "cursor_param": "cursor",
    "raise_on_repeated_cursor": True,
}


@frozen
class SlashResumeConfig:
    cursor: str


def invoice_with_id(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "id": row["invoice"]["id"]}


def virtual_account_with_id(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "id": row["virtualAccount"]["id"]}


def client_config(config: SlashSourceConfig) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "api_key": config.api_key, "name": "X-API-Key", "location": "header"},
        "headers": {"x-legal-entity": config.legal_entity_id} if config.legal_entity_id else {},
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def validate_credentials(config: SlashSourceConfig, schema_name: str | None) -> tuple[bool, str | None]:
    # Balances need an account ID in the path, so probe the account listing they fan out from.
    probe = "accounts" if schema_name is None or schema_name == "account_balances" else schema_name
    path = schema_for_resource(ENDPOINTS, probe)
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
    if endpoint == "account_balances":
        return account_balances_source(config, team_id, job_id)

    params: dict[str, Any] = {}
    if endpoint == "transactions" and should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = db_incremental_field_last_value
        if isinstance(watermark, str):
            watermark = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
        if watermark.tzinfo is None:
            watermark = watermark.replace(tzinfo=UTC)
        params["filter:from_date"] = int(watermark.timestamp() * 1000)
    if endpoint == "virtual_accounts":
        params["filter:includeClosedAccounts"] = "true"

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "items",
        "data_selector_required": True,
        "paginator": "single_page" if endpoint == "accounts" else CURSOR_PAGINATOR,
    }
    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    if endpoint == "invoices":
        resource_config["data_map"] = invoice_with_id
    elif endpoint == "virtual_accounts":
        resource_config["data_map"] = virtual_account_with_id

    rest_config: RESTAPIConfig = {"client": client_config(config), "resources": [resource_config]}
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


def account_balances_source(config: SlashSourceConfig, team_id: int, job_id: str) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": client_config(config),
        "resources": [
            {
                "name": "accounts",
                "endpoint": {
                    "path": ENDPOINTS["accounts"],
                    "data_selector": "items",
                    "data_selector_required": True,
                    "paginator": "single_page",
                },
            },
            {
                "name": "account_balances",
                "endpoint": {
                    "path": ENDPOINTS["account_balances"],
                    "params": {"accountId": {"type": "resolve", "resource": "accounts", "field": "id"}},
                    "data_selector": "balances",
                    "data_selector_required": True,
                    "paginator": "single_page",
                },
            },
        ],
    }
    resources = {resource.name: resource for resource in rest_api_resources(rest_config, team_id, job_id, None)}
    resource = resources["account_balances"]
    return SourceResponse(
        name="account_balances",
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS["account_balances"],
    )
