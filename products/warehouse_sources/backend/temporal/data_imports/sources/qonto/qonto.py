from datetime import datetime
from typing import Any
from urllib.parse import quote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qonto import QontoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
)


@frozen
class QontoResumeConfig:
    paginator_state: dict[str, Any]


def validate_credentials(
    config: QontoSourceConfig, api_version: str, schema_name: str | None
) -> tuple[bool, str | None]:
    if any("\r" in value or "\n" in value for value in (config.login, config.secret_key)):
        return False, AUTH_ERROR

    with make_tracked_session() as session:
        response = session.get(
            f"https://thirdparty.qonto.com/{api_version}/organization",
            auth=APIKeyAuth(api_key=f"{config.login}:{config.secret_key}"),
            timeout=30,
        )
    if response.status_code == 401:
        return False, AUTH_ERROR
    if response.status_code == 403:
        return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
    response.raise_for_status()
    return True, None


def account_for_request(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "request_id": quote(str(row["id"]), safe="")}


def transaction_with_account(row: dict[str, Any]) -> dict[str, Any]:
    row["bank_account_id"] = row.pop("_bank_accounts_id")
    return row


def get_resource(name: str, incremental: bool, last_value: str | datetime | None) -> EndpointResource:
    if name not in ENDPOINTS:
        raise ValueError(f"Unknown Qonto table: {name}")
    path, selector = ENDPOINTS[name]
    params: dict[str, Any] = {}
    if name != "bank_accounts":
        params["per_page"] = 100
    if name in INCREMENTAL_FIELDS:
        params["sort_by"] = "updated_at:desc"
        if incremental and last_value is not None:
            watermark = parse_datetime_value(last_value)
            if watermark is None:
                raise ValueError("Invalid Qonto incremental timestamp")
            params["updated_at_from"] = watermark.isoformat()
    if name == "transactions":
        # The account belongs in the path because the framework uses paths to identify resume checkpoints.
        path += "?bank_account_id={bank_account_id}"
        params["bank_account_id"] = {"type": "resolve", "resource": "bank_accounts", "field": "request_id"}
        params["status[]"] = ["pending", "declined", "completed", "reversed"]

    endpoint: Endpoint = {
        "path": path,
        "data_selector": selector,
        "data_selector_required": True,
        "params": params,
        "paginator": "single_page"
        if name == "bank_accounts"
        else PageNumberPaginator(base_page=1, total_path="meta.total_pages"),
    }
    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "endpoint": endpoint,
    }
    if name == "transactions":
        resource["include_from_parent"] = ["id"]
        resource["data_map"] = transaction_with_account
    return resource


def qonto_source(
    config: QontoSourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[QontoResumeConfig],
    incremental: bool,
    last_value: str | datetime | None,
) -> SourceResponse:
    resource = get_resource(endpoint, incremental, last_value)
    resources: list[str | EndpointResource] = [resource]
    if endpoint == "transactions":
        parent = get_resource("bank_accounts", False, None)
        parent["data_map"] = account_for_request
        resources.insert(0, parent)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://thirdparty.qonto.com/{api_version}/",
            "auth": APIKeyAuth(api_key=f"{config.login}:{config.secret_key}"),
            "request_timeout": 30,
        },
        "resources": resources,
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(QontoResumeConfig(paginator_state=state))

    result = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    selected = next(item for item in result if item.name == endpoint)
    return SourceResponse(
        name=endpoint,
        items=lambda: selected,
        primary_keys=["bank_account_id", "id"] if endpoint == "transactions" else ["id"],
        sort_mode="desc",
    )
