import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser as dateutil_parser
from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    BasePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import PARTNERIZE_ENDPOINTS

PARTNERIZE_BASE_URL = "https://api.partnerize.com"
# The report endpoints page at a fixed server-side size of 300 rows (echoed in the response's
# `limit` field) with no documented way to override it; we read the echoed value defensively.
REPORT_PAGE_LIMIT = 300
# start_date is a required parameter on the report endpoints, so full-refresh syncs use a fixed
# floor that predates the platform (Performance Horizon, now Partnerize, launched in 2010).
DEFAULT_START_DATE = "2010-01-01T00:00:00Z"


@dataclasses.dataclass
class PartnerizeResumeConfig:
    # Report endpoints resume from the row offset within the current date window; the window
    # itself is recomputed deterministically from the job's incremental inputs.
    offset: int | None = None
    # List endpoints resume from the hypermedia next-page URL.
    next_url: str | None = None


def _format_start_date(value: Any) -> str:
    """Coerce an incremental watermark to the ISO-8601 format the report endpoints document."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    if isinstance(value, str) and value:
        # Watermarks read back from the warehouse arrive as "YYYY-MM-DD HH:MM:SS" strings.
        try:
            return _format_start_date(dateutil_parser.parse(value))
        except (ValueError, OverflowError):
            return DEFAULT_START_DATE
    return DEFAULT_START_DATE


class _ReportOffsetPaginator(BasePaginator):
    """Offset pagination for Partnerize report endpoints.

    The reports page at a fixed server-side size echoed in the response's ``limit`` field with no
    documented override, so only ``offset`` is sent and the page size is read back per page; a page
    shorter than that limit ends the window. ``offset`` advances by the number of rows returned so a
    resumed run re-fetches from the next unseen page (merge dedupes the boundary).
    """

    def __init__(self, offset: int = 0) -> None:
        super().__init__()
        self.offset = offset

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        try:
            page_limit = response.json().get("limit")
        except Exception:
            page_limit = None
        if not isinstance(page_limit, int) or page_limit <= 0:
            page_limit = REPORT_PAGE_LIMIT

        # A short (or empty) page marks the end of the window.
        if len(rows) < page_limit:
            self._has_next_page = False
            return

        self.offset += len(rows)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state advanced it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


class _NextPagePaginator(BaseNextUrlPaginator):
    """Follows a Partnerize list endpoint's ``hypermedia.pagination.next_page`` cursor.

    The session carries the Basic auth header, so the cursor is only followed when it stays on
    Partnerize: a relative path (resolved against the API base) or an absolute URL under the API
    host. Anything else (an attacker-tampered response pointing at an internal host) ends the list
    without following it. An empty page also terminates so a lingering cursor can't loop forever.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        next_page = ((body.get("hypermedia") or {}).get("pagination") or {}).get("next_page")
        if not isinstance(next_page, str) or not next_page or not rows:
            self._has_next_page = False
            return

        if next_page.startswith("/"):
            self._next_url = f"{PARTNERIZE_BASE_URL}{next_page}"
        elif next_page.startswith(f"{PARTNERIZE_BASE_URL}/"):
            self._next_url = next_page
        else:
            self._has_next_page = False
            return

        self._has_next_page = True


def _make_unwrap(item_key: Optional[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Strip Partnerize's single-key item wrapper (e.g. ``{"campaign": {...}}``).

    When the wrapper key is absent or its value isn't a dict the item passes through unmodified.
    """

    def unwrap(item: dict[str, Any]) -> dict[str, Any]:
        if item_key:
            inner = item.get(item_key)
            if isinstance(inner, dict):
                return inner
        return item

    return unwrap


def partnerize_source(
    application_key: str,
    user_api_key: str,
    publisher_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PartnerizeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PARTNERIZE_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    params: dict[str, Any] = {}
    paginator: BasePaginator
    initial_paginator_state: Optional[dict[str, Any]] = None

    if config.kind == "report":
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            params["start_date"] = _format_start_date(db_incremental_field_last_value)
            # Rows at exactly the boundary timestamp are re-fetched; merge dedupes them on the
            # primary key.
            if incremental_field is not None:
                params.update(config.incremental_field_params.get(incremental_field, {}))
        else:
            params["start_date"] = DEFAULT_START_DATE
        paginator = _ReportOffsetPaginator()
        if resume is not None and resume.offset is not None:
            initial_paginator_state = {"offset": resume.offset}
    else:
        paginator = _NextPagePaginator()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PARTNERIZE_BASE_URL,
            # Auth (Basic) is supplied via the framework auth config so its secret is redacted from
            # raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": application_key, "password": user_api_key},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                # Strip Partnerize's single-key item wrapper (e.g. {"campaign": {...}}) per row.
                "data_map": _make_unwrap(config.item_key),
                "endpoint": {
                    "path": config.path.format(publisher_id=publisher_id),
                    "params": params,
                    "data_selector": config.data_key,
                    # A 200 whose data key is missing or not a list is treated as a transient bad
                    # shape and retried, rather than silently syncing 0 rows.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if config.kind == "report":
            if state.get("offset") is not None:
                resumable_source_manager.save_state(PartnerizeResumeConfig(offset=int(state["offset"])))
        elif state.get("next_url"):
            resumable_source_manager.save_state(PartnerizeResumeConfig(next_url=state["next_url"]))

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
        # The report endpoints document no ordering guarantee and accept no sort parameter, so the
        # incremental watermark only commits once a sync completes ("desc" semantics) instead of
        # checkpointing after every batch, which would risk skipping rows on an interrupted sync.
        sort_mode="desc" if config.kind == "report" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(application_key: str, user_api_key: str, publisher_id: str) -> tuple[bool, str | None]:
    # A single probe of the configured partner account validates the key pair and the publisher ID
    # for every endpoint at once.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(application_key, user_api_key)),
        f"{PARTNERIZE_BASE_URL}/user/publisher/{publisher_id}",
        headers={"Accept": "application/json"},
        auth=HTTPBasicAuth(application_key, user_api_key),
        timeout=15,
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Partnerize API credentials. Check your user application key and user API key."
    if status in (403, 404):
        return False, f"Your Partnerize credentials do not have access to publisher '{publisher_id}'."
    if status is not None:
        return False, f"Partnerize returned HTTP {status}"
    return False, "Could not validate Partnerize credentials"
