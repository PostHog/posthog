from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import TOGETHER_AI_ENDPOINTS

TOGETHER_AI_BASE_URL = "https://api.together.xyz/v1"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def together_ai_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]

    resource_endpoint: dict[str, Any] = {
        "path": endpoint_config.path,
        # Together's list endpoints are inconsistent: fine-tunes/files/endpoints wrap rows in
        # {"data": [...]}, batches/evaluations/models return a bare array. `data_selector` pins each
        # endpoint's known shape; requiring it means a changed/error 200 body fails loud instead of
        # silently syncing zero rows (a wrapped endpoint that stops wrapping, or vice versa).
        "data_selector_required": True,
    }
    if endpoint_config.data_selector is not None:
        resource_endpoint["data_selector"] = endpoint_config.data_selector
    if endpoint_config.params:
        resource_endpoint["params"] = dict(endpoint_config.params)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TOGETHER_AI_BASE_URL,
            # Non-secret content header only; the Bearer token is supplied via the framework auth
            # config below so its value is redacted from logs and raised error messages.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # Every list endpoint returns its whole collection in one un-paginated response.
            "paginator": SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            cast(
                "EndpointResource",
                {
                    "name": endpoint,
                    "endpoint": resource_endpoint,
                },
            )
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, db_incremental_field_last_value)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        column_hints=resource.column_hints,
    )


def get_status_code(api_key: str, endpoint: str | None = None) -> int:
    """Cheap probe used by credential validation. Returns the HTTP status code."""
    if endpoint is not None and endpoint in TOGETHER_AI_ENDPOINTS:
        endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]
        path = endpoint_config.path
        params: dict[str, str] | None = endpoint_config.params or None
    else:
        # Files is account-scoped and small — a cheap token check.
        path = "/files"
        params = None

    url = f"{TOGETHER_AI_BASE_URL}{path}"
    response = make_tracked_session(redact_values=(api_key,)).get(
        url, params=params, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code
