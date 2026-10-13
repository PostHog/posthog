from typing import Any, Optional

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.faire.settings import (
    BASE_URL,
    FAIRE_ENDPOINTS,
    FaireEndpointConfig,
)


@frozen
class FaireResumeConfig:
    """Immutable resume-cursor state passed between incremental sync runs."""

    cursor: str


def incremental_param(field_name: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": field_name,
        "initial_value": None,
    }


class FairePaginator(BasePaginator):
    """Faire pages the first request with `limit` (plus any static filters); once a response
    returns a `cursor`, every later request must carry only `cursor`/`limit` — Faire's docs say
    the cursor and the original filter params (`updated_at_min`, `sku`, `sort_by`, ...) can't be
    combined in the same request, so they're dropped as soon as a cursor shows up. Absence of a
    `cursor` in the response means there's no next page.
    """

    def __init__(self, limit: int, filter_params: tuple[str, ...]) -> None:
        super().__init__()
        self._limit = limit
        self._filter_params = filter_params
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self._limit
        if self._cursor is not None:
            self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None
        cursor = body.get("cursor") if isinstance(body, dict) else None
        if cursor:
            self._cursor = cursor
            self._has_next_page = True
        else:
            self._cursor = None
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def _apply_cursor(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        for key in self._filter_params:
            request.params.pop(key, None)
        request.params.pop("page", None)
        request.params["cursor"] = self._cursor
        request.params["limit"] = self._limit

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self._cursor = str(cursor)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"FairePaginator(limit={self._limit})"


def _build_params(config: FaireEndpointConfig, should_use_incremental_field: bool) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.static_params)
    if config.supports_incremental and should_use_incremental_field:
        params[config.incremental_param] = incremental_param("updated_at")
    return params


def faire_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FaireResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FAIRE_ENDPOINTS[endpoint]

    endpoint_def: Endpoint
    if config.is_single_object:
        # `/brands/profile` returns a single object rather than a paginated list.
        endpoint_def = {
            "path": config.path,
            "data_selector": "$",
            "paginator": SinglePagePaginator(),
        }
    else:
        endpoint_def = {
            "path": config.path,
            "params": _build_params(config, should_use_incremental_field),
            "data_selector": config.response_key,
            "paginator": FairePaginator(limit=config.page_size, filter_params=config.filter_params),
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": "X-FAIRE-ACCESS-TOKEN",
                "location": "header",
            },
            # The token rides in a custom header, not Authorization; don't let a redirect
            # replay it to a different host.
            "allow_redirects": False,
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint.lower(),
                "endpoint": endpoint_def,
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if not config.is_single_object and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; save AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FaireResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if config.supports_incremental else None,
        resume_hook=None if config.is_single_object else save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe `/brands/profile` to confirm the access token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/brands/profile",
        headers={"X-FAIRE-ACCESS-TOKEN": api_key, "Accept": "application/json"},
        # The token rides in a custom header, not Authorization — don't let a redirect replay it
        # to a different host.
        allow_redirects=False,
    )
