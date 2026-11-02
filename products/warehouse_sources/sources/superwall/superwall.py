from typing import Any, cast
from urllib.parse import quote

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.superwall import (
    SuperwallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.settings import (
    BASE_URL,
    ENDPOINTS,
    PRIMARY_KEYS,
)


@frozen
class SuperwallResumeConfig:
    cursor: str


class SuperwallPaginator(JSONResponseCursorPaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if body.get("has_more") is False:
            self._has_next_page = False
            return
        if body.get("has_more") is not True:
            raise ValueError("Superwall response has no valid has_more flag")
        super().update_state(response, data)
        if not self.has_next_page:
            raise ValueError("Superwall response has_more is true but has no next cursor")


def get_resource(config: SuperwallSourceConfig, name: str, api_version: str) -> EndpointResource:
    settings = schema_for_resource(ENDPOINTS, name)
    path = settings.path.replace("{project_id}", quote(config.project_id, safe=""))
    params: dict[str, Any] = dict(settings.params)
    if "{project_id}" not in settings.path:
        params[settings.scope_param] = getattr(config, settings.scope_param)
    endpoint: Endpoint = {
        "path": f"/{api_version}/{path}",
        "params": params,
        "data_selector": "data",
        "data_selector_required": True,
    }
    if settings.pagination == "single_page":
        endpoint["paginator"] = "single_page"
    else:
        params["limit"] = 100
        endpoint["paginator"] = SuperwallPaginator(
            cursor_path="iterator" if settings.pagination == "iterator" else "data[-1].id",
            cursor_param="iterator" if settings.pagination == "iterator" else "starting_after",
            raise_on_repeated_cursor=True,
        )
    return {
        "name": name,
        "table_name": name,
        "primary_key": PRIMARY_KEYS[name],
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": endpoint,
    }


def probe_credentials(config: SuperwallSourceConfig, schema_name: str | None, api_version: str) -> Response:
    endpoint = cast(Endpoint, get_resource(config, schema_name, api_version)["endpoint"]) if schema_name else None
    params = dict(endpoint.get("params") or {}) if endpoint else {}
    if "limit" in params:
        params["limit"] = 1
    with make_tracked_session(redact_values=(config.api_key,)) as session:
        return session.get(
            f"{BASE_URL}{endpoint['path'] if endpoint else f'/{api_version}/projects'}",
            params=params,
            headers={"Authorization": f"Bearer {config.api_key}", "Accept": "application/json"},
            timeout=10,
        )


def superwall_source(
    config: SuperwallSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SuperwallResumeConfig],
    api_version: str,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.api_key},
            "headers": {"Accept": "application/json"},
            "request_timeout": 30,
            "retry_budget_seconds": 120,
            "retry_after_max_seconds": 60,
        },
        "resources": [get_resource(config, endpoint, api_version)],
    }
    initial_state: dict[str, Any] | None = None
    if settings.pagination != "single_page" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"cursor": resume.cursor}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(SuperwallResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_keys=[settings.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
        supports_resume=settings.pagination != "single_page",
    )
