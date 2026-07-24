import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import LATTICE_ENDPOINTS

LATTICE_HOSTS = {
    "us": "https://api.latticehq.com",
    "emea": "https://api.emea.latticehq.com",
}
# Lattice's default page size is only 10; always request the max of 100.
PAGE_SIZE = 100


@dataclasses.dataclass
class LatticeResumeConfig:
    # Lattice cursor pagination: pass the previous page's endingCursor as
    # startingAfter; static params are rebuilt deterministically on resume.
    starting_after: str


class LatticeCursorPaginator(BasePaginator):
    """Lattice cursor pagination: the next page's ``startingAfter`` is the previous
    page's ``endingCursor``. Pagination stops as soon as ``hasMore`` is false, the
    body carries no ``endingCursor``, or the page returned no rows — the last of
    which guards against a server that keeps advertising more with an empty page."""

    def __init__(self, cursor_param: str = "startingAfter") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def init_request(self, request: Request) -> None:
        # Seed a resumed run's first request with the saved cursor.
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        ending_cursor = body.get("endingCursor") if isinstance(body, dict) else None
        has_more = body.get("hasMore") if isinstance(body, dict) else None
        if data and has_more and ending_cursor:
            self._cursor_value = ending_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True


def _base_url(region: str) -> str:
    host = LATTICE_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Lattice region: {region}")
    return host


def validate_credentials(region: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is valid with a cheap one-user probe.

    Keys inherit the creating user's privileges, so a key may lack access to a
    specific stream (403); only 401 means the key itself is bad."""
    try:
        base_url = _base_url(region)
    except ValueError as e:
        return False, str(e)

    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url}/v1/users?{urlencode({'limit': 1})}",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    if status is None:
        # Transport failures (timeouts, connection resets) are not auth failures;
        # don't mislabel the key as invalid.
        return False, "Could not reach Lattice"
    if status == 401:
        return False, "Invalid Lattice API key"
    return True, None


def lattice_source(
    region: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LatticeResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LATTICE_ENDPOINTS[endpoint]
    base_url = _base_url(region)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Auth is supplied via the framework auth config so its value is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            "paginator": LatticeCursorPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.starting_after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(LatticeResumeConfig(starting_after=str(state["cursor"])))

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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
