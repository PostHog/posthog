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
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.settings import HUMANITIX_ENDPOINTS

HUMANITIX_BASE_URL = "https://api.humanitix.com/v1"
# The list endpoints accept pageSize 1..100; 100 minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm the API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/events"


@dataclasses.dataclass
class HumanitixResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `_id`.
    next_page: int = 1


class HumanitixPaginator(BasePaginator):
    """Page-number pagination over the Humanitix `{total, page, pageSize, <list_key>[]}` envelope.

    Terminates on a short/empty page, or once the pages fetched cover the reported item ``total`` —
    the latter saving the extra empty-page request the built-in `PageNumberPaginator` would pay when
    the total is an exact multiple of the page size. Resumable: the saved page seeds the first request.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page = page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        # A short/empty page is the last page — no further rows to fetch.
        if len(items) < self.page_size:
            self._has_next_page = False
            return

        # A full page whose running count already covers the reported total ends the sync without
        # paying for an extra empty page. `self.page` is still the page just fetched here.
        try:
            total = response.json().get("total")
        except Exception:
            total = None
        if isinstance(total, int) and self.page * self.page_size >= total:
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
        return {"next_page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("next_page")
        if next_page is not None:
            self.page = int(next_page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"HumanitixPaginator(page={self.page})"


def _headers() -> dict[str, str]:
    # Auth (the `x-api-key` header) is supplied via the framework auth config so its value is redacted
    # from logs and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def humanitix_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HumanitixResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HUMANITIX_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HUMANITIX_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "x-api-key", "location": "header"},
            "paginator": HumanitixPaginator(page_size=PAGE_SIZE),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"pageSize": PAGE_SIZE},
                    "data_selector": config.list_key,
                    # The row array is always present in the envelope; missing it means a malformed
                    # response, so fail loud rather than silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page > 1:
            initial_paginator_state = {"next_page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `_id`) rather than skipping it.
        if state and state.get("next_page") is not None:
            resumable_source_manager.save_state(HumanitixResumeConfig(next_page=int(state["next_page"])))

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


def validate_credentials(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[bool, str | None]:
    """Probe a single list endpoint to validate the account-wide API key.

    The key is account-wide, so one probe validates access to every list endpoint. Maps 401/403 to a
    bad-key message, any other non-200 to its status, and an unreachable probe to a generic message.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{HUMANITIX_BASE_URL}{path}?page=1&pageSize=1",
        headers={"x-api-key": api_key, **_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Humanitix API key"
    if status is None:
        return False, "Could not validate Humanitix API key"
    return False, f"Humanitix returned HTTP {status}"
