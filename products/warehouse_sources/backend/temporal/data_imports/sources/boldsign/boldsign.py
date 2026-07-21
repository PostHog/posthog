import dataclasses
from typing import Any, Optional

import structlog
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import (
    BOLDSIGN_ENDPOINTS,
    BoldSignEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

logger = structlog.get_logger(__name__)

# BoldSign serves separate US and EU regional hosts; the account decides which one is live.
BOLDSIGN_HOSTS = {
    "us": "https://api.boldsign.com",
    "eu": "https://api-eu.boldsign.com",
}
PAGE_SIZE = 100
# Page-number access is capped at 10,000 records; document/list pages past it via NextCursor.
RECORD_CURSOR_THRESHOLD = 10_000


@dataclasses.dataclass
class BoldSignResumeConfig:
    # Page-number position for standard pagination.
    page: int = 1
    # Set once we cross the 10,000-record page cap on document/list and switch to cursor paging.
    # BoldSign describes this as an opaque value; the concrete type (int vs str) is unverified.
    next_cursor: str | int | None = None
    # Running total used to know when to switch to cursor paging.
    records_fetched: int = 0


def _base_url(region: str) -> str:
    host = BOLDSIGN_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid BoldSign region: {region}")
    return host


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-KEY": api_key,
        "Accept": "application/json",
    }


class BoldSignPaginator(BasePaginator):
    """Page-number pagination with BoldSign's 10,000-record page-number cap.

    Standard pages advance ``Page``; once the running record count crosses the cap, endpoints that
    support it (document/list) switch to cursor paging via ``NextCursor`` (taken from the last
    row's ``cursor`` field, with ``Page`` reset to 1). Endpoints without cursor support stop at
    the cap rather than loop.
    """

    def __init__(self, endpoint: str, supports_cursor: bool) -> None:
        super().__init__()
        self._endpoint = endpoint
        self._supports_cursor = supports_cursor
        self._page = 1
        self._next_cursor: str | int | None = None
        self._records_fetched = 0

    def _inject_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["Page"] = self._page
        request.params["PageSize"] = PAGE_SIZE
        if self._next_cursor is not None:
            request.params["NextCursor"] = self._next_cursor

    def init_request(self, request: Request) -> None:
        self._inject_params(request)

    def update_request(self, request: Request) -> None:
        self._inject_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if not items:
            self._has_next_page = False
            return

        self._records_fetched += len(items)

        # A short page means we've reached the end.
        if len(items) < PAGE_SIZE:
            self._has_next_page = False
            return

        if self._records_fetched >= RECORD_CURSOR_THRESHOLD:
            if not self._supports_cursor:
                # Page-number access is capped at 10k and this endpoint can't cursor past it.
                logger.warning(
                    f"BoldSign: {self._endpoint} reached the 10,000-record page-number cap; "
                    "remaining records are not synced (endpoint has no cursor pagination)."
                )
                self._has_next_page = False
                return
            last = items[-1]
            last_cursor = last.get("cursor") if isinstance(last, dict) else None
            # No (or non-advancing) cursor means we can't make progress; stop rather than loop.
            if last_cursor is None or last_cursor == self._next_cursor:
                self._has_next_page = False
                return
            self._next_cursor = last_cursor
            self._page = 1
        else:
            self._page += 1

        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {
            "page": self._page,
            "next_cursor": self._next_cursor,
            "records_fetched": self._records_fetched,
        }

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._page = int(state.get("page") or 1)
        self._next_cursor = state.get("next_cursor")
        self._records_fetched = int(state.get("records_fetched") or 0)
        self._has_next_page = True

    def __str__(self) -> str:
        return f"BoldSignPaginator(page={self._page}, next_cursor={self._next_cursor})"


def validate_credentials(region: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is genuine with one cheap, low-privilege list call."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_base_url(region)}/v1/document/list?Page=1&PageSize=1",
        headers=_get_headers(api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid BoldSign API key"
    if status is None:
        # A network error (timeout, connection failure) is not an auth problem — don't misreport
        # it as an invalid key and send the user on a fruitless key-rotation hunt.
        return False, "Could not reach BoldSign"
    return False, f"Unexpected response from BoldSign (status {status})"


def boldsign_source(
    region: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BoldSignResumeConfig],
) -> SourceResponse:
    config: BoldSignEndpointConfig = BOLDSIGN_ENDPOINTS[endpoint]

    paginator: BasePaginator
    if config.paginated:
        paginator = BoldSignPaginator(endpoint=endpoint, supports_cursor=config.supports_cursor)
    else:
        # `brand/list` returns the full set in one response with no pagination params.
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(region),
            # The API key is supplied via the framework auth config so its value is redacted
            # from logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": dict(config.extra_params),
                    # A missing data key is treated as an empty page (not an error), matching the
                    # API's occasional key-less empty responses.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {
                "page": resume.page,
                "next_cursor": resume.next_cursor,
                "records_fetched": resume.records_fetched,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next position and never skips a page — the prior state still points at the
        # just-yielded page, which merge dedupes on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(
                BoldSignResumeConfig(
                    page=int(state["page"]),
                    next_cursor=state.get("next_cursor"),
                    records_fetched=int(state.get("records_fetched") or 0),
                )
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every BoldSign endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Full refresh only — BoldSign timestamps are int64 epoch values, not datetimes, so there
        # is no stable datetime column to partition on.
        partition_mode=None,
    )
