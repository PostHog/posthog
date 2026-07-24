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
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.settings import ROCKETLANE_ENDPOINTS

ROCKETLANE_BASE_URL = "https://api.rocketlane.com/api/1.0"
# The list endpoints cap `pageSize` at 100 (values above the cap fall back to 100), so 100 minimises
# round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an api-key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


@dataclasses.dataclass
class RocketlaneResumeConfig:
    # Opaque cursor for the next page. Rocketlane returns a `nextPageToken` alongside `hasMore`; a
    # crashed full-refresh sync resumes from the last token it persisted. Note: Rocketlane tokens are
    # only valid for ~15 minutes, so a long-stalled resume may need to restart from the first page —
    # merge dedupes on the primary key either way.
    page_token: Optional[str] = None


def _headers() -> dict[str, str]:
    # Auth (the raw key in an `api-key` header, no "Bearer " prefix) is supplied via the framework
    # auth config so its value is redacted from logs and error messages; only the non-secret accept
    # header is set here.
    return {"Accept": "application/json"}


class RocketlaneCursorPaginator(BasePaginator):
    """Follows Rocketlane's `pagination.nextPageToken` cursor via a `pageToken` query param.

    Terminates when the API reports `hasMore=false`, stops handing back a token, or returns an empty
    page (the last guards against a server-side cursor bug that would otherwise loop forever). The
    built-in cursor paginator only inspects the token, so it can't reproduce the empty-page/`hasMore`
    stops the source relies on — hence this small local subclass. Resumable: the saved cursor points
    at the next unfetched page, so a crash re-fetches from there (merge dedupes on the primary key).
    """

    def __init__(self) -> None:
        super().__init__()
        self._page_token: Optional[str] = None

    def _apply(self, request: Request) -> None:
        # Omit `pageToken` on the first request; an empty token returns page 1.
        if self._page_token:
            if request.params is None:
                request.params = {}
            request.params["pageToken"] = self._page_token

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends the stream even if the API keeps advertising a cursor.
        if not data:
            self._has_next_page = False
            return
        try:
            body = response.json()
        except Exception:
            body = {}
        pagination = body.get("pagination") or {} if isinstance(body, dict) else {}
        next_token = pagination.get("nextPageToken")
        # Stop when the API says there are no more pages or stops handing back a cursor.
        if not pagination.get("hasMore") or not next_token:
            self._has_next_page = False
            return
        self._page_token = next_token
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page_token": self._page_token} if self._has_next_page and self._page_token else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        token = state.get("page_token")
        if token:
            self._page_token = token
            self._has_next_page = True

    def __str__(self) -> str:
        return "RocketlaneCursorPaginator()"


def rocketlane_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RocketlaneResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ROCKETLANE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ROCKETLANE_BASE_URL,
            "headers": _headers(),
            # Rocketlane expects the raw key in an `api-key` header — framework auth redacts it.
            "auth": {"type": "api_key", "api_key": api_key, "name": "api-key", "location": "header"},
            "paginator": RocketlaneCursorPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"pageSize": PAGE_SIZE},
                    "data_selector": "data",
                    # `data` is always present in a well-formed list response; a 200 body without it
                    # means the shape changed — fail loud rather than silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_token:
            initial_paginator_state = {"page_token": resume.page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the token pointing at the next page (the already-yielded pages are persisted) — merge
        # dedupes the re-pulled page on the primary key.
        if state and state.get("page_token"):
            resumable_source_manager.save_state(RocketlaneResumeConfig(page_token=state["page_token"]))

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
    """Probe a single list endpoint to validate the api-key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise. The api-key is account-wide, so one probe
    validates access to every list endpoint.
    """
    session = make_tracked_session(headers={"api-key": api_key, **_headers()}, redact_values=(api_key,))
    try:
        response = session.get(f"{ROCKETLANE_BASE_URL}{path}", params={"pageSize": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Rocketlane: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Rocketlane returned HTTP {response.status_code}"

    return 200, None
