from collections.abc import Callable
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    resolve_request_url,
    rest_api_resource,
)
from products.warehouse_sources.sources.together_ai.settings import TOGETHER_AI_ENDPOINTS, TogetherAIEndpointConfig

TOGETHER_AI_BASE_URL = "https://api.together.xyz/v1"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": TOGETHER_AI_BASE_URL,
        # Non-secret content header only; the Bearer token is supplied via the framework auth
        # config below so its value is redacted from logs and raised error messages.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        # Every list endpoint returns its whole collection in one un-paginated response.
        "paginator": SinglePagePaginator(),
    }


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for name in fields:
            row.pop(name, None)
        return row

    return _mapper


def _top_level_resource(
    api_key: str,
    endpoint: str,
    endpoint_config: TogetherAIEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> Any:
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

    resource_config: dict[str, Any] = {"name": endpoint, "endpoint": resource_endpoint}
    if endpoint_config.excluded_fields:
        resource_config["data_map"] = _drop_fields(endpoint_config.excluded_fields)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [cast("EndpointResource", resource_config)],
    }
    return rest_api_resource(rest_config, team_id, job_id, db_incremental_field_last_value)


def together_ai_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]

    resource: Any
    if endpoint_config.fanout is not None:
        parent_config = TOGETHER_AI_ENDPOINTS[endpoint_config.fanout.parent_name]
        resource = build_dependent_resource(
            endpoint_configs=TOGETHER_AI_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            parent_endpoint_extra={"data_selector": parent_config.data_selector, "data_selector_required": True},
            child_endpoint_extra={"data_selector": endpoint_config.data_selector, "data_selector_required": True},
            page_size_param=None,
        )
    else:
        resource = _top_level_resource(
            api_key, endpoint, endpoint_config, team_id, job_id, db_incremental_field_last_value
        )

    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=resource.column_hints,
    )


def get_status_code(api_key: str, endpoint: str | None = None) -> int:
    """Cheap probe used by credential validation. Returns the HTTP status code."""
    if endpoint is not None and endpoint in TOGETHER_AI_ENDPOINTS:
        endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]
        if endpoint_config.fanout is not None:
            # A per-job endpoint needs a job id; the parent listing proves the same access.
            endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint_config.fanout.parent_name]
        path = endpoint_config.path
        params: dict[str, str] | None = endpoint_config.params or None
    else:
        # Files is account-scoped and small — a cheap token check.
        path = "/files"
        params = None

    url = resolve_request_url(TOGETHER_AI_BASE_URL, path)
    response = make_tracked_session(redact_values=(api_key,)).get(
        url, params=params, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code
