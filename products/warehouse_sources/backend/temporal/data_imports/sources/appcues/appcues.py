import re
from datetime import UTC, datetime
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.settings import BASE_URLS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appcues import (
    AppcuesSourceConfig,
)

REQUEST_TIMEOUT_SECONDS = 30
RETRY_BUDGET_SECONDS = 240


def account_url(config: AppcuesSourceConfig, api_version: str) -> str:
    if config.region not in BASE_URLS:
        raise ValueError("Select the US or EU region for your Appcues account.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", config.account_id):
        raise ValueError("Enter the Appcues account ID from your account settings.")
    if not config.api_key or not config.api_secret or not (config.api_key.isascii() and config.api_secret.isascii()):
        raise ValueError("Enter a valid Appcues API key and secret.")
    if ":" in config.api_key:
        raise ValueError("Enter the Appcues API key and secret in separate fields.")
    if api_version != "v2":
        raise ValueError("This Appcues API version is not supported. Reconnect the source with version v2.")
    return f"{BASE_URLS[config.region]}/{api_version}/accounts/{config.account_id}/"


def probe_credentials(config: AppcuesSourceConfig, endpoint: str, api_version: str) -> None:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    client = RESTClient(
        base_url=account_url(config, api_version),
        auth=HttpBasicAuth(username=config.api_key, password=config.api_secret),
        headers={"Accept": "application/json"},
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=10,
        retry_budget_seconds=RETRY_BUDGET_SECONDS,
        retry_after_max_seconds=RETRY_BUDGET_SECONDS,
    )
    with client.session:
        next(client.paginate(settings.path, data_selector_required=True), None)


def normalize_created_at(item: dict[str, Any]) -> dict[str, Any]:
    created_at = item.get("created_at")
    # Experience endpoints use Unix milliseconds; older catalogs use ISO 8601 strings.
    if isinstance(created_at, int | float) and not isinstance(created_at, bool):
        item["created_at"] = datetime.fromtimestamp(created_at / 1000, tz=UTC)
    return item


def appcues_source(config: AppcuesSourceConfig, inputs: SourceInputs, api_version: str) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": account_url(config, api_version),
            "auth": {"type": "http_basic", "username": config.api_key, "password": config.api_secret},
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "retry_budget_seconds": RETRY_BUDGET_SECONDS,
            "retry_after_max_seconds": RETRY_BUDGET_SECONDS,
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "table_name": inputs.schema_name,
                "write_disposition": "replace",
                "columns": {"created_at": {"data_type": "timestamp"}},
                "endpoint": {
                    "path": settings.path,
                    "paginator": "single_page",
                    "data_selector_required": True,
                },
            }
        ],
    }
    resource = rest_api_resource(rest_config, inputs.team_id, inputs.job_id, None).add_map(normalize_created_at)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        column_hints=resource.column_hints,
        partition_keys=[settings.partition_key],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        partition_count=1,
        sort_mode=None,
        supports_resume=False,
    )
