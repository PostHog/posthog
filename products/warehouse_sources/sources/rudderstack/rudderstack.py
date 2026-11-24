from datetime import UTC, datetime, timedelta
from typing import Any

from requests import Response

from products.warehouse_sources.sources.rudderstack._config import RudderStackSourceConfig
from products.warehouse_sources.sources.rudderstack.settings import (
    BASE_URLS,
    CATALOG_MAX_PAGES,
    ENDPOINTS,
    USAGE_MAX_LOOKBACK_DAYS,
    USAGE_REFRESH_DAYS,
    RudderStackEndpoint,
)
from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    ClientConfig,
    Endpoint,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceInputs,
    SourceResponse,
    build_dependent_resource,
    format_datetime,
    frozen,
    make_tracked_session,
    resolve_incremental_start,
    rest_api_resource,
    schema_for_resource,
)


@frozen
class RudderStackResumeConfig:
    paginator_state: dict[str, Any]


class RudderStackCatalogLimitError(ValueError):
    pass


class RudderStackCatalogPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        payload = response.json()
        total = payload["total"]
        page_size = payload["pageSize"]
        if not isinstance(total, int) or total < 0 or not isinstance(page_size, int) or page_size <= 0:
            raise ValueError("RudderStack returned invalid catalog pagination metadata")
        # The catalog caps requests at 50 pages, so a larger collection cannot produce a complete full refresh.
        if total > page_size * CATALOG_MAX_PAGES:
            raise RudderStackCatalogLimitError("RudderStack catalog exceeds the 50-page API limit")
        super().update_state(response, data)
        if (self.page - 1) * page_size >= total:
            self._has_next_page = False


def usage_start(should_use_incremental_field: bool, last_value: Any, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    max_lookback = timedelta(days=USAGE_MAX_LOOKBACK_DAYS)
    start = resolve_incremental_start(
        should_use_incremental_field,
        last_value,
        default=max_lookback,
        lookback=timedelta(days=USAGE_REFRESH_DAYS),
        floor=(current - max_lookback).date(),
        now=current,
    )
    return format_datetime(start, "date")


def endpoint_params(
    endpoint: RudderStackEndpoint,
    should_use_incremental_field: bool = False,
    last_value: Any = None,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(endpoint.params)
    if endpoint.usage_window:
        params["start"] = usage_start(should_use_incremental_field, last_value)
    return params


def endpoint_config(
    endpoint: RudderStackEndpoint,
    api_version: str,
    should_use_incremental_field: bool = False,
    last_value: Any = None,
) -> Endpoint:
    return {
        "path": endpoint.path.replace("/v2/", f"/{api_version}/", 1),
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "params": endpoint_params(endpoint, should_use_incremental_field, last_value),
        "paginator": RudderStackCatalogPaginator()
        if endpoint.paginator == "catalog"
        else {"type": "json_response", "next_url_path": "paging.next"}
        if endpoint.paginator == "json_response"
        else "single_page",
    }


def endpoint_extra(endpoint: RudderStackEndpoint, api_version: str) -> Endpoint:
    config = endpoint_config(endpoint, api_version)
    config.pop("params", None)
    return config


def missing_organization_token_message(endpoint: str) -> str:
    return f"Add an organization Service Access Token to sync the {endpoint} table."


def token_for_endpoint(config: RudderStackSourceConfig, endpoint: str | None) -> str:
    if endpoint and endpoint in ENDPOINTS and ENDPOINTS[endpoint].organization_token:
        if not config.organization_access_token:
            raise ValueError(missing_organization_token_message(endpoint))
        return config.organization_access_token
    return config.access_token


def probe_credentials(config: RudderStackSourceConfig, schema_name: str | None, api_version: str) -> int:
    endpoint = schema_for_resource(ENDPOINTS, schema_name) if schema_name else None
    if endpoint and endpoint.fanout:
        endpoint = ENDPOINTS[endpoint.fanout.parent_name]
    path = endpoint.path.replace("/v2/", f"/{api_version}/", 1) if endpoint else f"/{api_version}/workspace"
    token = token_for_endpoint(config, schema_name)
    with make_tracked_session(redact_values=(token,)) as session:
        response = session.get(
            f"{BASE_URLS[config.region]}{path}",
            auth=BearerTokenAuth(token),
            headers={"Accept": "application/json"},
            params=endpoint_params(endpoint) if endpoint else None,
            timeout=(10, 30),
            allow_redirects=False,
        )
        return response.status_code


def rudderstack_source(
    config: RudderStackSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[RudderStackResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client: ClientConfig = {
        "base_url": BASE_URLS[config.region],
        "auth": {"type": "bearer", "token": token_for_endpoint(config, inputs.schema_name)},
        "headers": {"Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 30),
        "retry_budget_seconds": 120,
        "retry_after_max_seconds": 60,
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(RudderStackResumeConfig(paginator_state=state))

    if endpoint.fanout:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=inputs.schema_name,
            fanout=endpoint.fanout,
            client_config=client,
            path_format_values={},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            parent_endpoint_extra=endpoint_extra(ENDPOINTS[endpoint.fanout.parent_name], api_version),
            child_endpoint_extra=endpoint_extra(endpoint, api_version),
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    else:
        incremental = inputs.should_use_incremental_field and bool(endpoint.incremental_fields)
        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": inputs.schema_name,
                    "table_format": "delta",
                    "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
                    "endpoint": endpoint_config(
                        endpoint, api_version, incremental, inputs.db_incremental_field_last_value
                    ),
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        sort_mode=None,
    )
