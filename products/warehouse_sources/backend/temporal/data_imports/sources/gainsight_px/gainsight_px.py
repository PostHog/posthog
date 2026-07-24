import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode

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
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    EPOCH_MILLIS_FIELDS,
    GAINSIGHT_PX_ENDPOINTS,
    GAINSIGHT_PX_HOSTS,
)

# Gainsight PX carries the API key in this custom header. Passing it through the framework `auth`
# (api_key/header) means its value is scrubbed from every raised error and captured sample.
API_KEY_HEADER = "X-APTRINSIC-API-KEY"


@dataclasses.dataclass
class GainsightPxResumeConfig:
    # Cursor token for scroll-paginated endpoints (users/accounts). None starts at the first page.
    scroll_id: str | None = None
    # Next page index for page-number-paginated endpoints (features/segments/…). None starts at 0.
    page_number: int | None = None


def _base_url(region: str) -> str:
    return GAINSIGHT_PX_HOSTS.get(region) or GAINSIGHT_PX_HOSTS["us"]


def _build_url(base: str, params: dict[str, Any]) -> str:
    return f"{base}?{urlencode(params)}" if params else base


def _normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    """Convert the API's epoch-millisecond date fields to real datetimes.

    The warehouse then types these columns as timestamps (useful for querying) and the partitioner
    reads the datetime directly rather than misinterpreting raw millis as epoch seconds. `bool` is
    excluded because it's an `int` subclass and no boolean field is a date.
    """
    for name in EPOCH_MILLIS_FIELDS:
        value = item.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            item[name] = datetime.fromtimestamp(value / 1000, tz=UTC)
    return item


class _ScrollPaginator(BasePaginator):
    """Scroll (cursor) pagination for users/accounts.

    Gainsight PX warns not to rely on `scrollId` becoming null, so the loop also stops when a page
    returns fewer records than requested. State points at the next scroll cursor; it is only offered
    for resume while another page remains, so a crash re-yields the last page (merge dedupes).
    """

    def __init__(self, page_size: int, scroll_id: Optional[str] = None) -> None:
        super().__init__()
        self._page_size = page_size
        self._scroll_id = scroll_id

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._scroll_id is not None:
            if request.params is None:
                request.params = {}
            request.params["scrollId"] = self._scroll_id

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            next_scroll_id = response.json().get("scrollId")
        except Exception:
            next_scroll_id = None

        records = data or []
        if len(records) < self._page_size or not next_scroll_id:
            self._has_next_page = False
            self._scroll_id = None
        else:
            self._scroll_id = next_scroll_id
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        if self._scroll_id is not None:
            request.params["scrollId"] = self._scroll_id

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._scroll_id is not None:
            return {"scroll_id": self._scroll_id}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        scroll_id = state.get("scroll_id")
        if scroll_id is not None:
            self._scroll_id = scroll_id
            self._has_next_page = True


class _PageNumberPaginator(BasePaginator):
    """Page-number pagination for features/segments/engagements/articles/kc_bots.

    These responses carry an `isLastPage` flag; we also stop on a short page as a belt-and-braces
    guard. State (the next page index) is offered for resume only while another page remains.
    """

    def __init__(self, page_size: int, page_number: int = 0) -> None:
        super().__init__()
        self._page_size = page_size
        self._page_number = page_number

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["pageNumber"] = self._page_number

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            is_last_page = bool(response.json().get("isLastPage"))
        except Exception:
            is_last_page = False

        records = data or []
        if is_last_page or len(records) < self._page_size:
            self._has_next_page = False
        else:
            self._page_number += 1
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["pageNumber"] = self._page_number

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page_number": self._page_number} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page_number = state.get("page_number")
        if page_number is not None:
            self._page_number = int(page_number)
            self._has_next_page = True


def gainsight_px_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GainsightPxResumeConfig],
) -> SourceResponse:
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]
    partition_key = config.partition_key

    paginator: BasePaginator
    if config.pagination == "scroll":
        paginator = _ScrollPaginator(page_size=config.page_size)
    else:
        paginator = _PageNumberPaginator(page_size=config.page_size)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(region),
            # Only the non-secret Accept header goes here; the API key rides on framework `auth` so
            # its value is redacted from errors and samples.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": API_KEY_HEADER, "location": "header"},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"pageSize": config.page_size},
                    "data_selector": config.data_key,
                },
                "data_map": _normalize_row,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "scroll" and resume.scroll_id is not None:
                initial_paginator_state = {"scroll_id": resume.scroll_id}
            elif config.pagination == "page" and resume.page_number is not None:
                initial_paginator_state = {"page_number": resume.page_number}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if config.pagination == "scroll" and state.get("scroll_id") is not None:
            resumable_source_manager.save_state(GainsightPxResumeConfig(scroll_id=str(state["scroll_id"])))
        elif config.pagination == "page" and state.get("page_number") is not None:
            resumable_source_manager.save_state(GainsightPxResumeConfig(page_number=int(state["page_number"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Gainsight PX endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, region: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        _build_url(f"{_base_url(region)}/accounts", {"pageSize": 1}),
        headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
    )
    return ok
