import re
import dataclasses
from datetime import UTC, date, datetime
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
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import (
    PER_PAGE,
    USERVOICE_ENDPOINTS,
)

USERVOICE_API_PATH = "/api/v2/admin"

# A single DNS label: letters, digits, hyphens (not leading/trailing). Rejects anything that could
# retarget the host (slashes, `@`, dots) so the stored token is only ever sent to `<subdomain>.uservoice.com`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclasses.dataclass
class UservoiceResumeConfig:
    # Opaque cursor token from `pagination.cursor`, when the account uses cursor pagination.
    cursor: str | None = None
    # 1-indexed page for the page-number fallback. Only one of `cursor`/`page` is set at a time.
    page: int | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce user input to a bare, validated UserVoice subdomain label.

    Accepts either the full host (``yourcompany.uservoice.com``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    token can never be retargeted away from ``<subdomain>.uservoice.com``.
    """
    cleaned = subdomain.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".uservoice.com")
    if not _SUBDOMAIN_RE.match(cleaned):
        raise ValueError(
            f"Invalid UserVoice account subdomain: {subdomain!r}. Enter just your subdomain, e.g. "
            "'yourcompany' for yourcompany.uservoice.com."
        )
    return cleaned


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.uservoice.com{USERVOICE_API_PATH}"


def _format_updated_after(value: Any) -> str:
    """Format an incremental cursor as the ISO8601 UTC string UserVoice expects for `updated_after`.

    UserVoice documents the ``YYYY-mm-ddThh:mm:ssZ`` shape, so we emit the ``Z`` suffix rather than the
    ``+00:00`` offset that ``isoformat()`` produces.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class UservoicePaginator(BasePaginator):
    """UserVoice list pagination: prefer the opaque ``pagination.cursor`` token; fall back to page
    numbers (``pagination.page``/``total_pages``); and finally to a full-page heuristic when the
    metadata is absent. Only one of ``cursor``/``page`` is ever carried in the request at a time.
    """

    def __init__(self) -> None:
        super().__init__()
        # The cursor/page to send on the NEXT request. Both None on a fresh start (the first request
        # carries only the static params), or seeded from saved resume state.
        self._cursor: Optional[str] = None
        self._page: Optional[int] = None

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        # Rebuild the pagination param from scratch each page so a stale cursor/page can't linger when
        # the mode changes (the Request object is reused across pages).
        request.params.pop("cursor", None)
        request.params.pop("page", None)
        if self._cursor is not None:
            request.params["cursor"] = self._cursor
        elif self._page is not None:
            request.params["page"] = self._page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        current_cursor = self._cursor
        current_page = self._page or 1
        item_count = len(data) if data is not None else 0

        try:
            pagination = response.json().get("pagination", {}) or {}
        except Exception:
            pagination = {}

        next_cursor: Optional[str] = None
        next_page: Optional[int] = None

        cursor = pagination.get("cursor")
        if cursor:
            next_cursor = str(cursor)
        else:
            page = pagination.get("page", pagination.get("current_page"))
            total_pages = pagination.get("total_pages")
            if isinstance(page, int) and isinstance(total_pages, int):
                if page < total_pages:
                    next_page = page + 1
            elif item_count >= PER_PAGE:
                # No usable metadata: a full page implies there may be more.
                next_page = current_page + 1

        if next_cursor is None and next_page is None:
            self._has_next_page = False
            return

        # Guard against a non-advancing cursor to avoid looping forever on the same page.
        if next_cursor is not None and next_cursor == current_cursor:
            self._has_next_page = False
            return

        self._cursor = next_cursor
        self._page = next_page
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {"cursor": self._cursor, "page": self._page}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._cursor = state.get("cursor")
        self._page = state.get("page")
        self._has_next_page = True


def uservoice_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[UservoiceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = USERVOICE_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"per_page": PER_PAGE}
    # Only the `updated_after`-capable endpoints filter server-side; everything else is full refresh.
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["updated_after"] = _format_updated_after(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            # Non-secret header only; the token rides the framework Bearer auth so it's redacted from logs.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": UservoicePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # UserVoice wraps each list under its plural resource name; a missing key is a
                    # legit zero-row page (data_selector not required, matching the old `.get(key, [])`).
                    "data_selector": config.response_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.cursor is not None or resume.page is not None):
            initial_paginator_state = {"cursor": resume.cursor, "page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key. Only persist while a next page remains.
        if state is not None:
            resumable_source_manager.save_state(
                UservoiceResumeConfig(cursor=state.get("cursor"), page=state.get("page"))
            )

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
        # UserVoice's list order isn't a documented, verifiable guarantee, and its feedback endpoints
        # tend to return newest-first. "desc" defers the incremental watermark write to successful job
        # end (see finalize_desc_sort_incremental_value), so a crashed mid-sync run can't advance the
        # watermark past rows it never fetched; the next run re-pulls from the old watermark and merge
        # dedupes. Full-refresh endpoints don't checkpoint a watermark, so their sort_mode is moot.
        sort_mode="desc" if config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, int | None]:
    """Probe UserVoice's suggestions list to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the subdomain is malformed so the caller can surface a precise message.
    """
    url = f"{_base_url(subdomain)}/suggestions?per_page=1"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
