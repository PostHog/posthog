import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import BUNNY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BUNNY_BASE_URL = "https://api.bunny.net"
# The list endpoints accept perPage 5..1000; 1000 minimises round trips for the typically small
# zone/library tables.
PER_PAGE = 1000
# Cheap endpoint used to confirm an account API key is genuine. The AccessKey is account-wide, so
# one probe validates access to every Core API list endpoint.
DEFAULT_PROBE_PATH = "/pullzone"


@dataclasses.dataclass
class BunnyResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `Id`.
    next_page: int = 1


class BunnyHasMoreItemsPaginator(PageNumberPaginator):
    """Page-number paginator that stops on bunny.net's explicit ``HasMoreItems`` flag.

    The built-in stop conditions don't fit: bunny.net reports total ITEMS (not pages) and an
    empty ``Items`` page with ``HasMoreItems: true`` must not end the sync, while a final page
    can be full — so neither ``total_path`` nor ``stop_after_empty_page`` matches the API's
    own termination signal.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self.page += 1
        try:
            body = response.json()
        except Exception:
            body = None
        self._has_next_page = isinstance(body, dict) and bool(body.get("HasMoreItems", False))


def bunny_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BunnyResumeConfig],
) -> SourceResponse:
    config = BUNNY_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BUNNY_BASE_URL,
            # The AccessKey travels via the framework auth config so its value is redacted from
            # logged URLs and captured samples; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": access_key, "name": "AccessKey", "location": "header"},
            # Always request page>=1 so the API returns the paginated envelope
            # ({Items, CurrentPage, TotalItems, HasMoreItems}); page=0 would return a bare array.
            "paginator": BunnyHasMoreItemsPaginator(base_page=1),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"perPage": PER_PAGE},
                    "data_selector": "Items",
                    # `Items` is always present in the paginated envelope; missing it means a
                    # malformed response, so fail loudly rather than silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while more pages remain; saved AFTER a page is yielded so a crash
        # re-fetches from the next page (already-yielded pages are persisted) and merge
        # dedupes the re-pulled page on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(BunnyResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every bunny.net endpoint is full refresh — no incremental cursor
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


def check_access(access_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[bool, Optional[int]]:
    """Probe a single list endpoint to validate the account API key.

    Returns ``(ok, status)``: ``status`` is the HTTP status of the probe (401/403 means an auth
    failure — bunny.net returns clean HTTP status codes, so no body sniffing is needed) or
    ``None`` when the probe couldn't connect at all.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_key,)),
        f"{BUNNY_BASE_URL}{path}?page=1&perPage=5",
        headers={"AccessKey": access_key, "Accept": "application/json"},
    )
