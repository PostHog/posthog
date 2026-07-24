import dataclasses
from typing import Any, Optional

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
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.settings import TAVUS_ENDPOINTS

TAVUS_BASE_URL = "https://tavusapi.com/v2"
# Tavus list endpoints paginate with `page` (0-indexed) and `limit`; a large limit minimises round
# trips for the typically small video/replica/persona/conversation tables.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/replicas"


@dataclasses.dataclass
class TavusResumeConfig:
    # Next page to fetch (0-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on the id.
    next_page: int = 0


def _probe_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


class TavusPageNumberPaginator(BasePaginator):
    """0-indexed ``page``/``limit`` pagination matching Tavus's list envelope.

    Termination mirrors the source it replaces: stop on a short (or empty) page, and stop once the
    running row count reaches the envelope's ``total_count`` (an off-by-one guard for the case where
    the final page is exactly full). Resume seeds the next page; ``seen`` restarts from zero on
    resume just as the original did (merge dedupes the re-pulled page on the primary key).
    """

    def __init__(self, limit: int, page: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.page = page
        self._seen = 0

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page
        request.params["limit"] = self.limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        page_len = len(data) if data is not None else 0
        self._seen += page_len

        # A short/empty page means the last page has been reached.
        if page_len < self.limit:
            self._has_next_page = False
            return

        # Also stop once the running count reaches the reported total, guarding against an
        # off-by-one extra request when the final page is exactly full.
        try:
            total_count = response.json().get("total_count")
        except Exception:
            total_count = None
        if total_count is not None and self._seen >= total_count:
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def tavus_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TavusResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TAVUS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TAVUS_BASE_URL,
            # Auth (the account-wide API key) travels via the framework auth config so its value is
            # redacted from logged URLs and sampled bodies; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
            "paginator": TavusPageNumberPaginator(limit=PAGE_SIZE),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "data",
                    # The list envelope always carries `data`; a 200 missing it means the response
                    # shape changed — fail loud instead of silently advancing past lost rows.
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(TavusResumeConfig(next_page=int(state["page"])))

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


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{TAVUS_BASE_URL}{path}?page=0&limit=1",
        headers=_probe_headers(api_key),
    )
    if ok:
        return 200, None
    if status is None:
        return 0, "Could not connect to Tavus"
    if status in (401, 403):
        return status, None
    return status, f"Tavus returned HTTP {status}"
