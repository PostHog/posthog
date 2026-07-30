import dataclasses
from typing import Any, Optional

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import SENDOWL_ENDPOINTS

SENDOWL_BASE_URL = "https://www.sendowl.com"
# SendOwl caps `per_page` at 50 (default 10); the largest page minimises round trips while
# staying under the documented ~1 request/second advisory.
PER_PAGE = 50
# Cheap endpoint used to confirm the credentials are genuine. The key pair is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v1/products"


@dataclasses.dataclass
class SendowlResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


class SendowlPaginator(BasePaginator):
    """Page-number pagination that stops on the first short (or empty) page.

    SendOwl exposes no ``has_more`` flag or total count, so a page returning fewer than
    ``per_page`` rows marks the end of the collection — identical to the hand-rolled loop's
    ``len(items) < per_page`` termination, so no extra empty-page request is issued. Resume
    snapshots the next page to fetch; ``init_request`` seeds it so a resumed run never re-fetches
    an earlier page.
    """

    def __init__(self, per_page: int, page: int = 1, page_param: str = "page") -> None:
        super().__init__()
        self.per_page = per_page
        self.page = page
        self.page_param = page_param

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # A short or empty page is the last one — there is no total or `has_more` flag to consult.
        if data is None or len(data) < self.per_page:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def _unwrap(wrapper_key: str):
    # SendOwl list endpoints return a bare JSON array of single-key wrapper objects, e.g.
    # `[{"product": {...}}, ...]`. Unwrap each item so downstream tables hold the flat record.
    # Subscript access fails fast if the wrapper key is missing rather than silently importing
    # the outer dict (which would lack the primary key and carry a nested object as a stray field).
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        return row[wrapper_key] if isinstance(row, dict) else row

    return _map


def sendowl_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SendowlResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SENDOWL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SENDOWL_BASE_URL,
            "headers": {"Accept": "application/json"},
            # HTTP Basic auth with the API key as username and the secret as password. Supplying it
            # via the framework auth config redacts the secret from any raised error/log.
            "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
            "paginator": SendowlPaginator(per_page=PER_PAGE),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PER_PAGE},
                    # A 200 body that isn't the expected bare array is treated as transient and
                    # retried, matching the hand-rolled loop's retryable-on-non-list behaviour.
                    "data_selector_malformed_retryable": True,
                },
                "data_map": _unwrap(config.wrapper_key),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page > 1:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last full page (merge dedupes on `id`) rather than skipping it. A final short page
        # leaves no next page, so nothing is saved for it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(SendowlResumeConfig(next_page=int(state["page"])))

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
    )


def check_access(api_key: str, api_secret: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, api_secret)),
        f"{SENDOWL_BASE_URL}{path}?page=1&per_page=1",
        auth=HTTPBasicAuth(api_key, api_secret),
        timeout=15,
    )
    if status is None:
        return 0, "Could not connect to SendOwl"
    if status in (401, 403):
        return status, None
    if not ok:
        return status, f"SendOwl returned HTTP {status}"
    return 200, None
