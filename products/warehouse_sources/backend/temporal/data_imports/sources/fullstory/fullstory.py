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

FULLSTORY_BASE_URL = "https://api.fullstory.com"

# Session/event data only exists behind Fullstory's async Data Export jobs;
# the v2 users listing is the one directly listable surface.
ENDPOINTS = ("users",)


@dataclasses.dataclass
class FullStoryResumeConfig:
    # v2 listings paginate with an opaque next_page_token.
    next_page_token: str


class FullStoryCursorPaginator(JSONResponseCursorPaginator):
    """v2 cursor paginator that also halts on an empty page.

    Fullstory carries the next cursor in the body (``next_page_token``) and the cursor in the
    ``page_token`` query param. Beyond the base "no cursor => stop", this also stops when a page
    returns no rows even if a cursor is present — mirroring the old ``not next_token or not items``
    guard against a cursor that never clears.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="next_page_token", cursor_param="page_token")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not data:
            self._has_next_page = False


def _auth_header(api_key: str) -> str:
    # Fullstory's scheme is the raw API key after "Basic" (not base64 creds).
    return f"Basic {api_key}"


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-user listing probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{FULLSTORY_BASE_URL}/v2/users",
        headers={"Authorization": _auth_header(api_key)},
    )
    return ok


def fullstory_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FULLSTORY_BASE_URL,
            # The raw key rides in the Authorization header value; framework auth redacts it from
            # any raised error message. Only non-secret headers would go in client `headers`.
            "auth": {"type": "api_key", "api_key": _auth_header(api_key), "name": "Authorization"},
            "paginator": FullStoryCursorPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": f"/v2/{endpoint}",
                    # A missing `results` key is treated as an empty page (not an error), matching the
                    # old `data.get("results", []) or []`.
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.next_page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FullStoryResumeConfig(next_page_token=state["cursor"]))

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
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
