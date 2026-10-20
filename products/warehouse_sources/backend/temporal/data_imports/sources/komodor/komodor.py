from typing import Any

from requests import Request
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.komodor import (
    KomodorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.komodor.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    PAGE_SIZE,
    PRIMARY_KEYS,
    REGION_URLS,
)


@frozen
class KomodorResumeConfig:
    cursor: str | int


class KomodorPaginator(JSONResponseCursorPaginator):
    def __init__(self, *, cursor_path: str, pagination_field: str) -> None:
        super().__init__(cursor_path=cursor_path, raise_on_repeated_cursor=True)
        self.pagination_field = pagination_field

    def update_request(self, request: Request) -> None:
        state = self.get_resume_state()
        if state is not None:
            if request.json is None:
                request.json = {}
            request.json.setdefault("pagination", {})[self.pagination_field] = state["cursor"]

    def init_request(self, request: Request) -> None:
        self.update_request(request)


def get_base_url(region: str, api_version: str) -> str:
    if region not in REGION_URLS:
        raise ValueError("Select a valid Komodor region: US or EU.")
    return f"{REGION_URLS[region]}/api/{api_version}/"


def validate_credentials(config: KomodorSourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        base_url = get_base_url(config.region, api_version)
    except ValueError as error:
        return False, str(error)

    client = RESTClient(
        base_url=base_url,
        auth=APIKeyAuth(api_key=config.api_key, name="X-API-KEY"),
        allow_redirects=False,
        request_timeout=(10, 60),
    )
    try:
        next(
            client.paginate(
                "services/search",
                method="POST",
                json={"pagination": {"pageSize": 1}},
                data_selector="data.services",
                data_selector_required=True,
                paginator=SinglePagePaginator(),
            ),
            None,
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return False, AUTH_ERRORS[f"{error.response.status_code} Client Error"]
        raise
    return True, None


def komodor_source(
    config: KomodorSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[KomodorResumeConfig],
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown Komodor table: {endpoint}")

    endpoint_config = ENDPOINTS[endpoint].copy()
    paginated = endpoint in ("services", "jobs")
    if paginated:
        endpoint_config["json"] = {"pagination": {"pageSize": PAGE_SIZE}}
        endpoint_config["paginator"] = KomodorPaginator(
            cursor_path="meta.token" if endpoint == "services" else "meta.nextPage",
            pagination_field="token" if endpoint == "services" else "page",
        )
    else:
        endpoint_config["paginator"] = "single_page"
    endpoint_config["data_selector_required"] = True

    initial_state: dict[str, Any] | None = None
    if paginated and resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None:
            initial_state = {"cursor": saved.cursor}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(KomodorResumeConfig(cursor=state["cursor"]))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(config.region, api_version),
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "X-API-KEY", "location": "header"},
            "allow_redirects": False,
            "request_timeout": (10, 60),
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config, "write_disposition": "replace"}],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if paginated else None,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        sort_mode=None,
        supports_resume=paginated,
    )
