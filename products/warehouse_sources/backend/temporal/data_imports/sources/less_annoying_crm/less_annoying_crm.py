import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    LESS_ANNOYING_CRM_ENDPOINTS,
    WIDE_WINDOW_END,
    WIDE_WINDOW_START,
    LessAnnoyingCRMEndpointConfig,
    LessAnnoyingCRMFanoutConfig,
)

# Single flat RPC endpoint — every call is a POST here with a {"Function", "Parameters"} body.
LESS_ANNOYING_CRM_BASE_URL = "https://api.lessannoyingcrm.com/v2/"

# The API caps MaxNumberOfResults at 10,000. We page at 500 (the API default) so each yielded page
# stays small; the pipeline batches across pages so a smaller page size costs only extra requests.
PAGE_SIZE = 500

REQUEST_TIMEOUT_SECONDS = 60

# Errors (including invalid credentials) come back as an envelope carrying ErrorCode / ErrorDescription
# — as an HTTP 400 body for bad requests, and defensively matched on any status. The 400 + "Invalid
# credentials" case surfaces a message the source's non-retryable map matches to disable the sync with
# actionable copy; any other error envelope fails loud rather than silently syncing 0 rows.
LESS_ANNOYING_CRM_RESPONSE_ACTIONS: list[ResponseAction] = [
    {
        "status_code": 400,
        "content": "Invalid credentials",
        "action": "raise",
        "message": "Less Annoying CRM API error: Invalid credentials.",
    },
    {
        "content": '"ErrorCode"',
        "action": "raise",
        "message": "Less Annoying CRM API returned an error response.",
    },
]


@dataclasses.dataclass
class LessAnnoyingCRMResumeConfig:
    # Next page number to request. Full refresh only, so page number is the entire cursor: on resume
    # we re-request the last saved page (merge dedupes on the primary key).
    page: int = 1
    # Fan-out tables only: the parent (pipeline / group) whose child pages `page` points into.
    parent_id: Optional[str] = None


class LessAnnoyingCRMPaginator(BasePaginator):
    """Page paginator for LACRM's RPC API.

    LACRM pages via ``Page`` nested inside the request body's ``Parameters`` object (not a query
    param), and signals more pages with a body-level ``HasMoreResults`` boolean, falling back to a
    short-page heuristic when the flag is absent. No built-in paginator writes into a nested body key
    or reads a boolean has-more flag, so this small subclass carries both plus resume on the page.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page = page

    def _inject_page(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        parameters = request.json.setdefault("Parameters", {})
        parameters["Page"] = self.page

    def init_request(self, request: Request) -> None:
        self._inject_page(request)

    def update_request(self, request: Request) -> None:
        self._inject_page(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        records = data or []
        try:
            body = response.json()
        except Exception:
            body = None
        # LACRM signals more pages via HasMoreResults. Fall back to a short-page heuristic if the flag
        # is absent so we never loop forever on an endpoint that omits it.
        has_more = body.get("HasMoreResults") if isinstance(body, dict) else None
        if has_more is None:
            has_more = len(records) >= self.page_size
        if not has_more or not records:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"LessAnnoyingCRMPaginator(page={self.page})"


def _build_parameters(config: LessAnnoyingCRMEndpointConfig) -> dict[str, Any]:
    """Build the static ``Parameters`` body for an endpoint. ``Page`` is injected per request by the
    paginator; everything here is constant for the whole sync."""
    parameters: dict[str, Any] = {}
    if config.paginated:
        parameters["MaxNumberOfResults"] = PAGE_SIZE
    if config.date_window_params:
        start_param, end_param = config.date_window_params
        parameters[start_param] = WIDE_WINDOW_START
        parameters[end_param] = WIDE_WINDOW_END
    if config.sort_by:
        parameters["SortBy"] = config.sort_by
    if config.sort_direction:
        parameters["SortDirection"] = config.sort_direction
    parameters.update(config.parameters)
    return parameters


def _rest_config(
    api_key: str,
    name: str,
    function: str,
    parameters: dict[str, Any],
    data_selector: Optional[str],
    paginator: BasePaginator,
) -> RESTAPIConfig:
    endpoint_def: Endpoint = {
        "path": "",
        "method": "POST",
        "json": {"Function": function, "Parameters": parameters},
        "data_selector": data_selector,
        "paginator": paginator,
        "response_actions": LESS_ANNOYING_CRM_RESPONSE_ACTIONS,
    }
    resource_def: EndpointResource = {
        "name": name,
        "endpoint": endpoint_def,
    }
    return {
        "client": {
            "base_url": LESS_ANNOYING_CRM_BASE_URL,
            # LACRM sends the raw API key as the Authorization header value (no Bearer prefix). Framework
            # auth redacts it from logs and error messages; only the non-secret content-type is set here.
            "headers": {"Content-Type": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
        },
        "resources": [resource_def],
    }


def _parent_rows(api_key: str, fanout: LessAnnoyingCRMFanoutConfig, team_id: int, job_id: str) -> list[dict[str, Any]]:
    paginator: BasePaginator = (
        LessAnnoyingCRMPaginator(page_size=PAGE_SIZE) if fanout.parent_paginated else SinglePagePaginator()
    )
    parameters: dict[str, Any] = {"MaxNumberOfResults": PAGE_SIZE} if fanout.parent_paginated else {}
    rest_config = _rest_config(
        api_key, "parents", fanout.parent_function, parameters, fanout.parent_data_selector, paginator
    )
    resource = rest_api_resource(rest_config, team_id, job_id, None)
    return [row for page in resource for row in page if row.get(fanout.parent_id_field)]


def _fanout_items(
    api_key: str,
    endpoint: str,
    config: LessAnnoyingCRMEndpointConfig,
    fanout: LessAnnoyingCRMFanoutConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LessAnnoyingCRMResumeConfig],
) -> Iterator[Any]:
    parents = _parent_rows(api_key, fanout, team_id, job_id)
    parent_ids = [str(parent[fanout.parent_id_field]) for parent in parents]

    start_index, start_page = 0, 1
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # A parent deleted since the checkpoint restarts the fan-out; merge dedupes the re-read rows.
        if resume is not None and resume.parent_id in parent_ids:
            start_index, start_page = parent_ids.index(resume.parent_id), resume.page

    for index in range(start_index, len(parents)):
        parent_id = parent_ids[index]

        def save_checkpoint(state: Optional[dict[str, Any]], parent_id: str = parent_id) -> None:
            if state and state.get("page") is not None:
                resumable_source_manager.save_state(
                    LessAnnoyingCRMResumeConfig(page=int(state["page"]), parent_id=parent_id)
                )

        page = start_page if index == start_index else 1
        # Every row of the previous parent is yielded, so a hand-off here resumes at this parent.
        resumable_source_manager.save_state(LessAnnoyingCRMResumeConfig(page=page, parent_id=parent_id))
        resumable_source_manager.safe_point()
        parameters = {**_build_parameters(config), **fanout.child_parameters(parents[index])}
        resource = rest_api_resource(
            _rest_config(
                api_key,
                endpoint,
                config.function,
                parameters,
                config.data_selector,
                LessAnnoyingCRMPaginator(page_size=PAGE_SIZE),
            ),
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"page": page} if page > 1 else None,
        )
        yield from resource


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine with the cheapest possible probe.

    ``GetUser`` takes no parameters and always returns the authenticated user, so it validates the
    key without touching any specific resource's read permissions. A bad key comes back as HTTP 400
    with an ErrorCode / ErrorDescription envelope."""
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.post(
            LESS_ANNOYING_CRM_BASE_URL,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            json={"Function": "GetUser", "Parameters": {}},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return False
        data = response.json()
        return not (isinstance(data, dict) and ("ErrorCode" in data or "ErrorDescription" in data))
    except Exception:
        return False


def less_annoying_crm_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LessAnnoyingCRMResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LESS_ANNOYING_CRM_ENDPOINTS[endpoint]
    partition_kwargs: dict[str, Any] = {
        "partition_count": 1,
        "partition_size": 1,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "month" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    fanout = config.fanout
    if fanout is not None:
        return SourceResponse(
            name=endpoint,
            items=lambda: _fanout_items(api_key, endpoint, config, fanout, team_id, job_id, resumable_source_manager),
            primary_keys=config.primary_keys,
            **partition_kwargs,
        )

    paginator: BasePaginator = (
        LessAnnoyingCRMPaginator(page_size=PAGE_SIZE) if config.paginated else SinglePagePaginator()
    )
    rest_config = _rest_config(
        api_key, endpoint, config.function, _build_parameters(config), config.data_selector, paginator
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(LessAnnoyingCRMResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
        **partition_kwargs,
    )
