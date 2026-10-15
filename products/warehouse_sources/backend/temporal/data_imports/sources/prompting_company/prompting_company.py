from datetime import UTC, date, datetime
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptingcompany import (
    PromptingCompanySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class PromptingCompanyResumeConfig:
    page: int


def request_params(
    config: PromptingCompanySourceConfig,
    name: str,
    watermark: date | datetime | str | None = None,
) -> dict[str, Any]:
    endpoint = schema_for_resource(ENDPOINTS, name)
    params: dict[str, Any] = {}
    if endpoint.product_scoped:
        params["productId"] = config.product_id
    if endpoint.paginated:
        params["pageSize"] = PAGE_SIZE
    if name == "published_content":
        params.update(status="published", orderBy="createdAt", orderByDirection="asc")
    elif name == "simulation_runs":
        params.update(orderBy="createdAt", order="asc")
    elif name == "share_of_voice":
        start = date.fromisoformat(config.start_date)
        if watermark is not None:
            start = max(start, date.fromisoformat(str(watermark)[:10]))
        params.update(
            start=start.isoformat(), end=datetime.now(UTC).date().isoformat(), granularity="day", rollingWindow=1
        )
    return params


def validate_credentials(config: PromptingCompanySourceConfig, schema_name: str | None) -> tuple[bool, str | None]:
    name = schema_name or "published_content"
    endpoint = schema_for_resource(ENDPOINTS, name)
    params = request_params(config, name)
    if endpoint.paginated:
        params.update(page=1, pageSize=1)
    if name == "share_of_voice":
        params["start"] = params["end"]
    auth = APIKeyAuth(api_key=config.api_key, name="x-api-key", location="header")
    with make_tracked_session(redact_values=auth.secret_values(), allow_redirects=False) as session:
        response = session.get(BASE_URL + endpoint.path, params=params, auth=auth, timeout=30, allow_redirects=False)
    if response.status_code == 401:
        return False, AUTH_ERROR
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, f"This table requires the `{endpoint.scope}` scope. Create a key with this read scope."
    if response.status_code == 404:
        return False, "The product was not found. Check the product ID and the API key's organization."
    response.raise_for_status()
    return True, None


def prompting_company_source(
    config: PromptingCompanySourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[PromptingCompanyResumeConfig],
) -> SourceResponse:
    name = inputs.schema_name
    endpoint = schema_for_resource(ENDPOINTS, name)
    params = request_params(
        config, name, inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
    )
    paginator = (
        PageNumberPaginator(base_page=1, total_path=endpoint.total_pages_path)
        if endpoint.paginated
        else SinglePagePaginator()
    )
    initial_state: dict[str, Any] | None = None
    if endpoint.paginated and manager.can_resume():
        saved = manager.load_state()
        if saved is not None:
            initial_state = {"page": saved.page}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and "page" in state:
            manager.save_state(PromptingCompanyResumeConfig(page=int(state["page"])))

    endpoint_config: Endpoint = {
        "path": endpoint.path,
        "params": params,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "paginator": paginator,
    }
    resource_config: EndpointResource = {"name": name, "endpoint": endpoint_config}
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "x-api-key", "api_key": config.api_key, "location": "header"},
            "request_timeout": 30,
            "allow_redirects": False,
        },
        "resources": [resource_config],
    }
    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        # The API does not guarantee date order for the share-of-voice series.
        sort_mode="desc" if name == "share_of_voice" else None,
        supports_resume=endpoint.paginated,
        on_complete=manager.clear_state if endpoint.paginated else None,
    )
