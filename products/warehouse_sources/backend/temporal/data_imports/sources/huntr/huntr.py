import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.settings import HUNTR_ENDPOINTS

HUNTR_BASE_URL = "https://api.huntr.co/org"
# The list endpoints accept a `limit`; the docs don't state a hard maximum, so 100 keeps each page
# reasonably sized while minimising round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an access token is genuine. The org access token is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/members"


@dataclasses.dataclass
class HuntrResumeConfig:
    # Cursor for the next page to fetch — Huntr returns the `id` of the last object on the page as
    # `next`, and passing it back fetches the following page. Cursor pagination is deterministic, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next: str | None = None


class HuntrCursorPaginator(JSONResponseCursorPaginator):
    """Huntr wraps results in ``{"data": [...], "next": "<cursor>"}``; ``next`` is the id of the last
    object and is passed back as the ``next`` query param. A missing/null ``next`` ends the collection.
    An empty page also terminates defensively so a lingering cursor can never produce an infinite loop.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not data:
            self._has_next_page = False


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def huntr_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HuntrResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HUNTR_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HUNTR_BASE_URL,
            # Only the non-secret Accept header goes here; auth (Bearer) is supplied via the framework
            # auth config so its value is redacted from logs and error messages.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": access_token},
            "paginator": HuntrCursorPaginator(cursor_path="next", cursor_param="next"),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                    # An unexpected 200-body shape (non-dict body, or `data` not a list) is treated as
                    # transient and reissued rather than failing the import.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next is not None:
            initial_paginator_state = {"cursor": resume.next}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(HuntrResumeConfig(next=str(state["cursor"])))

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
        column_hints=resource.column_hints,
    )


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the access token.

    The access token is organization-wide, so a single probe validates access to every list endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{HUNTR_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers=_headers(access_token),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Huntr access token"
    if status is not None:
        return False, f"Huntr returned HTTP {status}"
    return False, "Could not validate Huntr access token"
