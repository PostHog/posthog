from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.settings import (
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.axiom import AxiomSourceConfig


@frozen
class AxiomResumeConfig:
    offset: int


def validate_credentials(config: AxiomSourceConfig, schema_name: str | None = None) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=config.api_token),
        headers={"x-axiom-org-id": config.org_id} if config.org_id else {},
        paginator=SinglePagePaginator(),
        max_retry_attempts=1,
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    endpoints = [schema_for_resource(ENDPOINTS, schema_name)] if schema_name else list(ENDPOINTS.values())
    for endpoint in endpoints:
        path = endpoint.get("path")
        if path is None:
            raise ValueError("Axiom endpoint path is required")
        params = dict(endpoint.get("params") or {})
        if endpoint["paginator"] != "single_page":
            params["limit"] = 1
        try:
            list(client.paginate(path, params=params, data_selector_required=True))
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 403 and schema_name is None:
                continue
            if status in AUTH_ERRORS:
                return False, AUTH_ERRORS[status]
            raise
        return True, None
    return False, AUTH_ERRORS[403]


def axiom_source(
    config: AxiomSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[AxiomResumeConfig],
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    paginated = endpoint["paginator"] != "single_page"
    initial_state: dict[str, Any] | None = None
    if paginated and manager.can_resume():
        saved = manager.load_state()
        if saved is not None:
            initial_state = {"offset": saved.offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(AxiomResumeConfig(offset=int(state["offset"])))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.api_token},
            "headers": {"x-axiom-org-id": config.org_id} if config.org_id else {},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "primary_key": PRIMARY_KEYS,
                "write_disposition": "replace",
                "endpoint": {**endpoint, "data_selector": "", "data_selector_required": True},
            }
        ],
    }
    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint if paginated else None,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        on_complete=manager.clear_state if paginated else None,
        primary_keys=PRIMARY_KEYS,
        sort_mode=None,
        supports_resume=paginated,
    )
