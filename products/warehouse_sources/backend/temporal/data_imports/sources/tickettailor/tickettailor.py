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
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.settings import (
    TICKET_TAILOR_ENDPOINTS,
)

TICKET_TAILOR_BASE_URL = "https://api.tickettailor.com"
# List endpoints cap `limit` at 100; the largest page minimises round trips against the
# 5000 requests / 30 minutes rate limit.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. Keys are scoped to a whole box office,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/v1/events"


@dataclasses.dataclass
class TicketTailorResumeConfig:
    # Cursor for the next page: Ticket Tailor paginates by passing the last item's object id as
    # `starting_after` (lists are returned newest-first). A crashed sync resumes from the page
    # after the last one yielded; merge dedupes on `id`. `None` means start from the first page.
    cursor: str | None = None


class TicketTailorPaginator(BasePaginator):
    """Ticket Tailor cursor pagination.

    Lists are returned newest-first; the next page is fetched by sending the last item's object
    id as ``starting_after``. The body carries ``links.next`` (null on the last page), which is
    the authoritative stop signal — the cursor itself is always present while rows remain, so we
    must not infer termination from it.
    """

    def __init__(self) -> None:
        super().__init__()
        # `starting_after` id for the NEXT request; None means the (uncursored) first page.
        self._cursor: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["starting_after"] = self._cursor

    def init_request(self, request: Request) -> None:
        # Seed a resumed run (or a no-op on a fresh run where the cursor is still None).
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        links = body.get("links") if isinstance(body, dict) else None
        has_next = isinstance(links, dict) and bool(links.get("next"))
        # Advance only while the API reports another page AND this one carried rows; an empty page
        # or a null `links.next` terminates without issuing a further request.
        if has_next and data:
            self._cursor = data[-1]["id"]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def tickettailor_source(
    api_key: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[TicketTailorResumeConfig],
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = TICKET_TAILOR_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TICKET_TAILOR_BASE_URL,
            # Ticket Tailor authenticates via HTTP Basic with the API key as the username and no
            # password. Supplied through the framework auth config so the credential is redacted.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "headers": {"Accept": "application/json"},
            "paginator": TicketTailorPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                    # List endpoints wrap records in {"data": [...], "links": {...}}. A 200 whose
                    # body isn't that shape (non-dict, or missing/non-list `data`) is treated as a
                    # transient truncation and retried rather than ingested as a stray row.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(TicketTailorResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every endpoint is full refresh — see settings.py for why there is no cursor
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Not every object carries a stable creation timestamp (discounts, vouchers,
        # membership types), so we don't partition.
        partition_count=1,
        partition_size=1,
        # Lists are returned newest-first by object id. Inert while every endpoint is full
        # refresh, but declared so a future incremental cursor can't corrupt its watermark.
        sort_mode="desc",
    )


def validate_credentials(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[bool, str | None]:
    # The API key is box-office-wide, so a single probe validates access to every schema. Ticket
    # Tailor answers unauthenticated and invalid-key requests with 403 (it reserves 401 for
    # malformed auth headers) — both are permanent credential failures.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{TICKET_TAILOR_BASE_URL}{path}?limit=1",
        auth=HttpBasicAuth(username=api_key, password=""),
        timeout=15,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Ticket Tailor API key"
    if status is None:
        return False, "Could not validate Ticket Tailor API key"
    return False, f"Ticket Tailor returned HTTP {status}"
