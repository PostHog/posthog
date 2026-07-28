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
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.settings import SVIX_ENDPOINTS

SVIX_BASE_URL = "https://api.svix.com/api/v1"
# The list endpoints accept a `limit` of up to 250; the largest page minimises round trips.
PAGE_SIZE = 250
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/event-type"


@dataclasses.dataclass
class SvixResumeConfig:
    # Opaque cursor returned by the previous page. Svix cursor pagination is deterministic, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on
    # the primary key. `None` means start from the beginning.
    iterator: Optional[str] = None


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
    # and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class SvixCursorPaginator(BasePaginator):
    """Svix list endpoints paginate with an opaque ``iterator`` cursor and flag the last page with a
    ``done`` boolean, returning ``{"data": [...], "iterator": "...", "done": bool}``. The cursor is
    echoed even on the final page, so termination keys off ``done`` (a missing ``done`` is treated as
    terminal, matching ``data.get("done", True)``) plus a missing/null next cursor. A plain cursor
    paginator that stops only on a falsy cursor would loop forever here."""

    def __init__(self, cursor_param: str = "iterator") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Omit the cursor on the first request — Svix rejects an empty cursor value. Only inject when
        # a resume cursor was seeded.
        if self._cursor_value is not None:
            self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or body.get("done", True):
            self._has_next_page = False
            return
        cursor = body.get("iterator")
        if cursor is None:
            self._has_next_page = False
            return
        self._cursor_value = cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            self._inject(request)

    def _inject(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.cursor_param] = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"iterator": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("iterator")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"SvixCursorPaginator(cursor_param={self.cursor_param})"


def svix_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SvixResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SVIX_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SVIX_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": SvixCursorPaginator(),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                    # A 200 whose body isn't the expected `{"data": [...]}` envelope is treated as a
                    # transient bad shape and retried — matching the old SvixRetryableError raised on
                    # a non-dict body or a missing `data` key.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.iterator is not None:
            initial_paginator_state = {"iterator": resume.iterator}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint lands AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("iterator") is not None:
            resumable_source_manager.save_state(SvixResumeConfig(iterator=state["iterator"]))

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


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SVIX_BASE_URL}{path}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
        timeout=15,
    )
    if status is None:
        return 0, "Could not connect to Svix"
    if status in (401, 403):
        return status, None
    if status != 200:
        return status, f"Svix returned HTTP {status}"
    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Svix API key"
    return False, message or "Could not validate Svix API key"
