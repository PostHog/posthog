from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PERMISSION_ERROR,
    REQUEST_TIMEOUT,
)


@frozen
class GoLoginResumeConfig:
    page: int


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
    )
    try:
        next(client.paginate("/user", data_selector="$"))
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise
    return True, None


def gologin_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GoLoginResumeConfig],
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]
    initial_state: dict[str, Any] | None = None
    if endpoint == "profiles" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"page": resume.page}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and "page" in state:
            resumable_source_manager.save_state(GoLoginResumeConfig(page=int(state["page"])))

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config, "write_disposition": "replace"}],
    }
    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=["id"])
