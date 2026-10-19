from typing import Any, cast

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.settings import (
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
)


@frozen
class ReferralHeroResumeConfig:
    paginator_state: dict[str, Any] | None = None
    finished: bool = False


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(api_token),
        paginator=SinglePagePaginator(),
        request_timeout=(10, 60),
    )
    try:
        next(client.paginate(path="lists", params={"page": 1}, data_selector="data.lists", data_selector_required=True))
    except HTTPError as error:
        for pattern, message in AUTH_ERRORS.items():
            if pattern in str(error):
                return False, message
        raise
    return True, None


def _resource(name: str) -> EndpointResource:
    endpoint = ENDPOINTS[name]
    paginator: PaginatorConfig = (
        cast(
            PaginatorConfig,
            {
                "type": "page_number",
                "base_page": 1,
                "total_path": "data.pagination.total_pages",
            },
        )
        if endpoint.paginated
        else "single_page"
    )
    request: Endpoint = {
        "path": endpoint.path,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "paginator": paginator,
    }
    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "endpoint": request,
    }
    if name != "lists":
        resource["include_from_parent"] = ["uuid"]
        request["params"] = {"uuid": {"type": "resolve", "resource": "lists", "field": "uuid"}}
    return resource


def referralhero_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ReferralHeroResumeConfig],
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown ReferralHero table: {endpoint}")

    saved = manager.load_state()
    primary_keys = list(ENDPOINTS[endpoint].primary_keys) or None
    if saved and saved.finished:
        return SourceResponse(name=endpoint, items=lambda: iter(()), primary_keys=primary_keys)

    def checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(ReferralHeroResumeConfig(paginator_state=state, finished=state is None))
        manager.safe_point()

    resources: list[str | EndpointResource] = (
        [_resource(endpoint)] if endpoint == "lists" else [_resource("lists"), _resource(endpoint)]
    )
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_token},
            "request_timeout": (10, 60),
        },
        "resources": resources,
    }
    built = rest_api_resources(
        config,
        team_id,
        job_id,
        None,
        resume_hook=checkpoint,
        initial_paginator_state=saved.paginator_state if saved else None,
    )
    resource = next(resource for resource in built if resource.name == endpoint)
    if endpoint != "lists":
        resource = resource.add_map(rename_parent_fields("lists", {"uuid": "list_uuid"}))
    return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=primary_keys)
