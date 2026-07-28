import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import DRIP_ENDPOINTS

DRIP_BASE_URL = "https://api.getdrip.com/v2"


@dataclasses.dataclass
class DripResumeConfig:
    next_page: int


class DripPaginator(BasePaginator):
    """Page-number pagination matching Drip's list endpoints.

    Drip returns a ``meta.total_pages`` block on its paginated endpoints; when present it is
    authoritative (fetch while ``page < total_pages``). For a paginated endpoint that omits ``meta``
    we fall back to "a full page implies there may be more", and a non-paginated endpoint
    (``per_page`` is None) always returns everything in a single response. The ``page`` param is sent
    on every request (including the single request to non-paginated endpoints), mirroring the
    original hand-rolled source exactly.
    """

    def __init__(self, per_page: Optional[int], page: int = 1) -> None:
        super().__init__()
        self.per_page = per_page
        self.page = page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        try:
            meta = response.json().get("meta") or {}
        except Exception:
            meta = {}
        total_pages = meta.get("total_pages")

        if total_pages is not None:
            has_next = self.page < total_pages
        elif self.per_page is not None:
            # No meta block: a full page implies there may be more; a partial/empty page ends it.
            has_next = len(items) >= self.per_page
        else:
            has_next = False

        if has_next:
            self.page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"next_page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("next_page")
        if next_page is not None:
            self.page = int(next_page)
            self._has_next_page = True


def _base_params(endpoint: str) -> dict[str, Any]:
    config = DRIP_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}
    if config.per_page is not None:
        params["per_page"] = config.per_page
    if config.sort is not None:
        params["sort"] = config.sort
    if config.direction is not None:
        params["direction"] = config.direction
    return params


def drip_source(
    api_token: str,
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DripResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DRIP_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{DRIP_BASE_URL}/{account_id}",
            "headers": {"Accept": "application/json"},
            # Drip uses HTTP Basic auth with the API token as the username and an empty password;
            # supplying it via the framework auth config keeps the token redacted from logs.
            "auth": {"type": "http_basic", "username": api_token, "password": ""},
            "paginator": DripPaginator(per_page=config.per_page),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _base_params(endpoint),
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_page") is not None:
            resumable_source_manager.save_state(DripResumeConfig(next_page=int(state["next_page"])))

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str, account_id: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{DRIP_BASE_URL}/{account_id}/subscribers?per_page=1",
        auth=HttpBasicAuth(username=api_token, password=""),
    )

    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Drip API token"
    if status == 404:
        return False, "Drip account ID not found. Please check your account ID."
    if status is None:
        return False, "Could not connect to the Drip API"
    return False, f"Drip API returned an unexpected status ({status})"
