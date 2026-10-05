from typing import Any

from requests import Response
from requests.exceptions import HTTPError, RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ticketmaster import (
    TicketmasterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ticketmaster.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    KEYWORD_ERROR,
    MAX_RESULTS,
    PAGE_SIZE,
    PRIMARY_KEYS,
    RESULT_LIMIT_ERROR,
)


@frozen
class TicketmasterResumeConfig:
    page: int


class TicketmasterPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=0, total_path="page.totalPages")

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        page = body.get("page") if isinstance(body, dict) else None
        if not isinstance(page, dict) or not all(
            isinstance(page.get(key), int) and page[key] >= 0 for key in ("totalElements", "totalPages")
        ):
            raise ValueError("Ticketmaster returned invalid pagination data. Try the sync again.")
        if page["totalElements"] > MAX_RESULTS or page["totalPages"] > MAX_RESULTS // PAGE_SIZE:
            raise ValueError(RESULT_LIMIT_ERROR)
        if not data and page["totalElements"] > 0 and self.page < page["totalPages"]:
            raise ValueError("Ticketmaster returned an empty page before the search ended. Try the sync again.")
        super().update_state(response, data)


def validate_credentials(config: TicketmasterSourceConfig, endpoint: str, api_version: str) -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, endpoint)
    if not config.keyword.strip():
        return False, KEYWORD_ERROR
    params: dict[str, str | int] = {"size": 1, "keyword": config.keyword.strip()}
    try:
        with make_tracked_session(redact_values=(config.api_key,)) as session:
            response = session.get(
                f"https://app.ticketmaster.com/discovery/{api_version}/{path}",
                auth=APIKeyAuth(api_key=config.api_key, name="apikey", location="query"),
                params=params,
                timeout=30,
                allow_redirects=False,
            )
    except RequestException as error:
        raise RequestException(f"Ticketmaster connection failed ({type(error).__name__}). Try again.") from None
    if response.status_code in AUTH_ERRORS:
        return False, AUTH_ERRORS[response.status_code]
    if response.status_code != 200:
        raise HTTPError(f"Ticketmaster request failed (HTTP {response.status_code}). Try again.", response=response)
    return True, None


def ticketmaster_source(
    config: TicketmasterSourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TicketmasterResumeConfig],
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    if not config.keyword.strip():
        raise ValueError(KEYWORD_ERROR)
    response_actions: list[ResponseAction] = []
    for status, message in AUTH_ERRORS.items():
        response_actions.append({"status_code": status, "action": "raise", "message": message})
    for status in range(400, 500):
        if status not in AUTH_ERRORS and status != 429:
            response_actions.append(
                {
                    "status_code": status,
                    "action": "raise",
                    "message": f"Ticketmaster request failed (HTTP {status}). Try again.",
                }
            )
    endpoint_config: Endpoint = {
        "path": path,
        "params": {"size": PAGE_SIZE, "keyword": config.keyword.strip(), "sort": "name,asc"},
        "data_selector": f"_embedded.{endpoint}",
        "response_actions": response_actions,
    }
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://app.ticketmaster.com/discovery/{api_version}/",
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "apikey", "location": "query"},
            "paginator": TicketmasterPaginator(),
            "request_timeout": 30,
            "allow_redirects": False,
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(TicketmasterResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page} if resume else None,
    )
    return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=PRIMARY_KEYS, sort_mode=None)
