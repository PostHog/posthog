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
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.settings import DOCUSEAL_ENDPOINTS

# DocuSeal runs two hosted regions on separate base URLs. There is no programmatic way to
# discover which region an account lives in, so the user picks it on the connection form.
DOCUSEAL_HOSTS: dict[str, str] = {
    "us": "https://api.docuseal.com",
    "eu": "https://api.docuseal.eu",
}
DEFAULT_REGION = "us"

# Max page size the API accepts (`limit`, capped server-side at 100).
PAGE_SIZE = 100


@dataclasses.dataclass
class DocusealResumeConfig:
    # The `after` cursor (a record id) used to fetch the page we're currently streaming. We persist
    # *this* page's cursor (not the next page's) so a crash mid-page resumes by re-fetching the same
    # page rather than skipping past rows still buffered but not yet yielded — merge dedupes the
    # re-pulled rows on the primary key. `None` means "start from the first page".
    after: int | None = None


def _base_url(region: str | None) -> str:
    return DOCUSEAL_HOSTS.get(region or DEFAULT_REGION, DOCUSEAL_HOSTS[DEFAULT_REGION])


class DocusealCursorPaginator(BasePaginator):
    """Walk DocuSeal's id-descending list endpoints backwards via the `after` cursor.

    DocuSeal orders list responses by `id` descending (newest first) and paginates *backwards*:
    `pagination.next` is the smallest id on the page, and passing it as `after` returns the next
    page of older (smaller-id) records. There is no server-side time filter, so this is a full
    walk newest -> oldest.

    Two DocuSeal-specific quirks make the built-in cursor paginator unsuitable, so this local
    subclass handles them:

    * Termination is a null `next` OR a short page (< `page_size`). DocuSeal's final page still
      carries a non-null `next` (its own smallest id), so without the short-page check we'd pay one
      extra empty request every sync.
    * Resume must persist the cursor of the page *currently* being streamed, not the next one, so a
      crash re-fetches that page rather than skipping rows still buffered but not yet durably
      written (merge dedupes the re-pulled rows on the primary key).
    """

    def __init__(self, page_size: int, cursor_param: str = "after") -> None:
        super().__init__()
        self.page_size = page_size
        self.cursor_param = cursor_param
        # Cursor used to fetch the request currently in flight (None => first page).
        self._current_after: Optional[int] = None
        # Cursor for the next request, discovered from `pagination.next`.
        self._pending_after: Optional[int] = None
        # Cursor of the page just processed — what we persist so a crash re-fetches it.
        self._resume_after: Optional[int] = None

    def _set_cursor(self, request: Request, value: Optional[int]) -> None:
        if value is None:
            return
        if request.params is None:
            request.params = {}
        request.params[self.cursor_param] = value

    def init_request(self, request: Request) -> None:
        # Seed the first request from a resumed cursor (no-op on a fresh start).
        self._set_cursor(request, self._current_after)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # The page in `data` was fetched with `_current_after`; persist THAT (see class docstring).
        self._resume_after = self._current_after
        try:
            body = response.json()
        except Exception:
            body = {}
        rows = data if data is not None else (body.get("data") or [])
        next_cursor = (body.get("pagination") or {}).get("next")
        # A null `next` or a short page (< page_size) both signal the end of the list.
        if not next_cursor or len(rows) < self.page_size:
            self._has_next_page = False
            self._pending_after = None
        else:
            self._has_next_page = True
            self._pending_after = next_cursor

    def update_request(self, request: Request) -> None:
        if self._has_next_page and self._pending_after is not None:
            self._current_after = self._pending_after
            self._set_cursor(request, self._current_after)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # The cursor of the page just yielded (None on the first page = restart from the top).
        return {"after": self._resume_after}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._current_after = state.get("after")


def docuseal_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DocusealResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DOCUSEAL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(region),
            # Auth (the X-Auth-Token API key) is supplied via the framework auth config so its value
            # is redacted from logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Auth-Token", "location": "header"},
            "paginator": DocusealCursorPaginator(page_size=PAGE_SIZE),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    # A missing `data` key is treated as an empty page (end of list), matching the
                    # hand-rolled `data.get("data", [])`, so this selector is intentionally not
                    # required.
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"after": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded, persisting the current page's cursor so a crash re-fetches it
        # (merge dedupes) rather than skipping buffered rows. `state` is None only on the last page.
        if state is not None:
            resumable_source_manager.save_state(DocusealResumeConfig(after=state.get("after")))

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
        # Rows arrive newest-first; declare it so the pipeline doesn't assume ascending order.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, region: str | None) -> tuple[bool, str | None]:
    """Confirm the API token is genuine with one cheap, low-limit list request.

    DocuSeal issues a single account-wide token (no per-resource scopes), so probing any list
    endpoint is sufficient. A 401 means the token is wrong; anything else reachable counts as valid.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_base_url(region)}/templates?limit=1",
        headers={"X-Auth-Token": api_key, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach DocuSeal. Check your network and try again."
    if status == 401:
        return False, "Invalid DocuSeal API key. Create a new key in your DocuSeal account settings and reconnect."
    return False, f"DocuSeal API returned an unexpected status ({status}) while validating credentials."
