from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.clever.settings import (
    CLEVER_BASE_URL,
    CLEVER_ENDPOINTS,
    CLEVER_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class CleverResumeConfig:
    starting_after: str


class CleverPaginator(BasePaginator):
    """Cursor pagination via Clever's `links` envelope.

    Every Clever list response carries a root-level `links` array; a `rel: "next"` entry's
    `uri` is a relative path whose query string carries the `starting_after` value for the
    next page. There is no absolute URL to follow, so the cursor value is extracted and
    re-injected as a param on the existing request rather than following the URI directly.
    """

    def __init__(self) -> None:
        super().__init__()
        self._starting_after: Optional[str] = None

    def init_request(self, request: Request) -> None:
        if self._starting_after is not None:
            if request.params is None:
                request.params = {}
            request.params["starting_after"] = self._starting_after

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        body = response.json()
        links = body.get("links") if isinstance(body, dict) else None
        next_uri = next((link.get("uri") for link in links if link.get("rel") == "next"), None) if links else None

        if not next_uri:
            self._has_next_page = False
            self._starting_after = None
            return

        starting_after = parse_qs(urlsplit(next_uri).query).get("starting_after", [None])[0]
        if not starting_after:
            # A `next` link without a `starting_after` value is not a shape we can resume
            # from, so stop rather than re-fetch the same page forever.
            self._has_next_page = False
            self._starting_after = None
            return

        self._starting_after = starting_after
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["starting_after"] = self._starting_after

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._starting_after is not None and self._has_next_page:
            return {"starting_after": self._starting_after}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        starting_after = state.get("starting_after")
        if starting_after is not None:
            self._starting_after = str(starting_after)
            self._has_next_page = True


def clever_source(
    bearer_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CleverResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    config = CLEVER_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": CLEVER_PAGE_SIZE}
    params.update(config.extra_params)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CLEVER_BASE_URL,
            "auth": {"type": "bearer", "token": bearer_token},
            "paginator": CleverPaginator(),
            # Clever responses carry student, guardian, and staff PII (names, DOBs, contact
            # info, addresses) that the name-based sample scrubbers aren't guaranteed to catch,
            # so keep raw bodies out of HTTP sample capture even where an operator enables it.
            "capture": False,
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
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Every Clever object is double-wrapped: the list envelope's `data` array
                    # holds one `{"data": {...fields...}, "links": [...]}` entry per row.
                    "data_selector": "data[*].data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"starting_after": resume.starting_after}
    elif should_use_incremental_field and db_incremental_field_last_value:
        # `starting_after` is both the pagination cursor and the cross-sync incremental
        # watermark for the /events delta feed: resuming from the last synced event id
        # picks the feed up where the previous sync left off.
        initial_paginator_state = {"starting_after": str(db_incremental_field_last_value)}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded, so a crash mid-sync re-yields the last page (merge
        # dedupes on `id`) instead of skipping it.
        if state and state.get("starting_after"):
            resumable_source_manager.save_state(CleverResumeConfig(starting_after=str(state["starting_after"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(bearer_token: str) -> tuple[bool, str | None]:
    try:
        response = make_tracked_session(redact_values=(bearer_token,)).get(
            f"{CLEVER_BASE_URL}/districts",
            headers={"Authorization": f"Bearer {bearer_token}"},
            params={"limit": 1},
        )
    except Exception:
        return False, "Could not reach Clever. Check your network connection and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid or expired bearer token. Check the district bearer token and try again."
    return False, f"Clever returned an unexpected error (status {response.status_code}). Please try again."
