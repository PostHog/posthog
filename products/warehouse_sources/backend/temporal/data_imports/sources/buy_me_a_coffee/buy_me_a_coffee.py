from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.settings import (
    API_BASE_URL,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse

AUTH_ERROR = "Your Buy Me a Coffee token is invalid or expired. Generate a new personal access token and reconnect."
PERMISSION_ERROR = "Your Buy Me a Coffee token cannot access this data. Check its read-only access and reconnect."


@frozen
class BuyMeACoffeeResumeConfig:
    page: int


def get_resource(endpoint: str) -> EndpointResource:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {
            "path": endpoint_config.path,
            "params": {"status": endpoint_config.status} if endpoint_config.status else {},
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": PageNumberPaginator(base_page=1, total_path="last_page"),
        },
    }


def validate_credentials(access_token: str, endpoint: str = "supporters") -> tuple[bool, str | None]:
    if not access_token or not access_token.isascii():
        return False, "Enter a valid Buy Me a Coffee personal access token."

    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    client = RESTClient(
        base_url=API_BASE_URL,
        auth=BearerTokenAuth(token=access_token),
        headers={"Accept": "application/json"},
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    params: dict[str, str | int] = {"page": 1}
    if endpoint_config.status:
        params["status"] = endpoint_config.status

    try:
        with client.session:
            next(
                client.paginate(
                    path=endpoint_config.path,
                    params=params,
                    paginator=SinglePagePaginator(),
                    data_selector="data",
                    data_selector_required=True,
                ),
                None,
            )
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise

    return True, None


def buy_me_a_coffee_source(
    access_token: str,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[BuyMeACoffeeResumeConfig],
) -> SourceResponse:
    endpoint = inputs.schema_name
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": {
            "base_url": API_BASE_URL,
            "auth": {"type": "bearer", "token": access_token},
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [get_resource(endpoint)],
    }
    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(BuyMeACoffeeResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_keys=[endpoint_config.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="desc",
    )
