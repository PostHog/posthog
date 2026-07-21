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
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.settings import JUSTSIFT_ENDPOINTS

JUSTSIFT_BASE_URL = "https://api.justsift.com/v1"
# Sift caps pageSize at 100 (default 10); 100 minimises round trips over a typically modest
# people directory and field catalog.
PAGE_SIZE = 100
# Cheap endpoint used to confirm a data token is genuine and can read people. The token is
# org-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/search/people"


@dataclasses.dataclass
class JustSiftResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on the
    # primary key.
    next_page: int = 1


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted from logs;
    # only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class JustSiftPaginator(PageNumberPaginator):
    """Sift ``page``/``pageSize`` pagination.

    Stops on a short or empty page, or once the reported total item count (``meta.totalLength`` —
    a count of ITEMS, not pages) has been covered, so a final exactly-full page doesn't provoke a
    spurious empty follow-up request. ``pageSize`` rides along as a static endpoint param; this
    paginator only advances ``page``.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends the sync (nothing more to fetch).
        if not data:
            self._has_next_page = False
            return

        page_just_fetched = self.page
        self.page += 1

        # A short page is the last page.
        if len(data) < PAGE_SIZE:
            self._has_next_page = False
            return

        # `meta.totalLength` is the total row count; once the pages fetched so far cover it there is
        # nothing left, so stop without paying for a spurious empty page.
        try:
            total = response.json().get("meta", {}).get("totalLength")
        except Exception:
            total = None
        if isinstance(total, int) and page_just_fetched * PAGE_SIZE >= total:
            self._has_next_page = False
            return

        self._has_next_page = True


def justsift_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JustSiftResumeConfig],
) -> SourceResponse:
    config = JUSTSIFT_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": JUSTSIFT_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": JustSiftPaginator(),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"pageSize": PAGE_SIZE},
                    "data_selector": "data",
                    # `data` is always present in the Sift envelope ({data, links, meta}); missing it
                    # means a malformed response — fail loud rather than silently syncing 0 rows.
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) and merge dedupes the re-pulled
        # page on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(JustSiftResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # full refresh only — Sift's list endpoints expose no server-side cursor
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
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the data token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise. Sift returns clean HTTP status codes for an
    invalid or scope-limited token, so no body sniffing is needed.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{JUSTSIFT_BASE_URL}{path}?page=1&pageSize=1",
        headers={"Authorization": f"Bearer {api_key}", **_non_secret_headers()},
    )
    if status is None:
        return 0, "Could not connect to Sift"
    if ok:
        return 200, None
    if status in (401, 403):
        return status, None
    return status, f"Sift returned HTTP {status}"
