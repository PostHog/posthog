import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import DEEL_ENDPOINTS

DEEL_BASE_URL = "https://api.letsdeel.com/rest/v2"
# Several Deel endpoints cap `limit` below 100, so stay safely under every cap.
PAGE_SIZE = 50


@dataclasses.dataclass
class DeelResumeConfig:
    # Offset-paginated endpoints persist the offset; the contracts keyset walk
    # persists Deel's opaque `after_cursor` instead.
    offset: Optional[int] = None
    cursor: Optional[str] = None


class DeelCursorPaginator(BasePaginator):
    """Keyset paginator for Deel's ``after_cursor`` endpoints (e.g. contracts).

    The next cursor lives at ``page.cursor`` in the body. Terminate when the response
    carries no next cursor OR returns no rows — Deel can echo a stale cursor on an
    exhausted keyset, so an empty page must stop the walk rather than loop.
    """

    def __init__(self, cursor_param: str = "after_cursor") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._cursor: Optional[str] = None

    def _inject(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def init_request(self, request: Request) -> None:
        # Applies a seeded resume cursor to the first request.
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        try:
            next_cursor = (response.json().get("page") or {}).get("cursor")
        except Exception:
            next_cursor = None
        if next_cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is valid with a cheap one-person listing probe.

    Scoped tokens may lack individual resource scopes (403); only 401 means the
    token itself is bad. A transient network failure surfaces as a distinct
    "could not reach Deel" error so it isn't mistaken for a bad token."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{DEEL_BASE_URL}/people?limit=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )

    if status is None:
        return False, "Could not reach Deel"
    if status == 401:
        return False, "Invalid Deel API token"
    return True, None


def deel_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DEEL_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    paginator: BasePaginator
    params: dict[str, Any]
    initial_paginator_state: Optional[dict[str, Any]]

    if config.pagination == "cursor":
        paginator = DeelCursorPaginator()
        params = {"limit": PAGE_SIZE}
        initial_paginator_state = (
            {"cursor": resume.cursor} if resume is not None and resume.cursor is not None else None
        )

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash
            # re-yields the last page (merge dedupes) rather than skipping it.
            if state and state.get("cursor") is not None:
                resumable_source_manager.save_state(DeelResumeConfig(cursor=str(state["cursor"])))

    else:
        # OffsetPaginator injects both limit and offset; termination is a short/empty page
        # (Deel exposes no dependable top-level total), matching the hand-rolled walk.
        paginator = OffsetPaginator(limit=PAGE_SIZE, total_path=None)
        params = {}
        initial_paginator_state = (
            {"offset": resume.offset} if resume is not None and resume.offset is not None else None
        )

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("offset") is not None:
                resumable_source_manager.save_state(DeelResumeConfig(offset=int(state["offset"])))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": DEEL_BASE_URL,
            # Bearer auth via the framework so the token is redacted from logs.
            "auth": {"type": "bearer", "token": api_token},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing `data` key is treated as an empty page (lenient), matching the
                    # hand-rolled `body.get("data", [])` — not a fail-loud like other sources.
                    "data_selector": "data",
                },
            }
        ],
    }

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
