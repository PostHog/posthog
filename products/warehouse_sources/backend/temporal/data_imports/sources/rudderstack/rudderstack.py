from typing import Any

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rudderstack import (
    RudderStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.settings import (
    BASE_URLS,
    CATALOG_MAX_PAGES,
    ENDPOINTS,
    RudderStackEndpoint,
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


def endpoint_config(endpoint: RudderStackEndpoint, api_version: str) -> Endpoint:
    return {
        "path": endpoint.path.replace("/v2/", f"/{api_version}/", 1),
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "params": dict(endpoint.params),
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


def token_for_endpoint(config: RudderStackSourceConfig, endpoint: str | None) -> str:
    if endpoint == "audit_logs":
        if not config.organization_access_token:
            raise ValueError("Add an organization Service Access Token to sync audit logs.")
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
            params=endpoint.params if endpoint else None,
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
        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": inputs.schema_name,
                    "table_format": "delta",
                    "write_disposition": "replace",
                    "endpoint": endpoint_config(endpoint, api_version),
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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint.partition_key],
        sort_mode=None,
    )
