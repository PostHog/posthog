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
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import E2B_ENDPOINTS

# E2B exposes a single global base URL; there are no regional hosts.
E2B_BASE_URL = "https://api.e2b.app"

# Cursor pagination: `limit` maxes out at 100, and the next cursor is returned in this response header.
E2B_PAGE_LIMIT = 100
NEXT_TOKEN_HEADER = "X-Next-Token"
NEXT_TOKEN_PARAM = "nextToken"

# E2B lets users stash arbitrary key/value data on a sandbox, and its own docs suggest keeping secrets
# (API keys, tokens) there. Writing it to the warehouse table would let anyone with table read access
# read credentials they can't see in the protected source config, so we drop it before ingesting.
SENSITIVE_FIELDS = ("metadata",)


def _scrub(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in SENSITIVE_FIELDS}


class E2BRetryableError(Exception):
    pass


@dataclasses.dataclass
class E2BResumeConfig:
    # Opaque cursor to fetch the next page from (E2B's `nextToken`). `None` starts at the first page.
    # A job only ever syncs one endpoint, so a single token slot is unambiguous.
    next_token: str | None = None


class HeaderCursorPaginator(BasePaginator):
    """E2B returns the next-page cursor in a response header (not the body), and expects it echoed
    back as a query param. No built-in paginator reads a cursor from a header, so this small subclass
    does — resumably. Terminates when the header is absent, or repeats the cursor just sent (a
    defensive guard against an endpoint that echoes the token instead of dropping it)."""

    def __init__(self, header_name: str = NEXT_TOKEN_HEADER, cursor_param: str = NEXT_TOKEN_PARAM) -> None:
        super().__init__()
        self.header_name = header_name
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request so a resumed run starts mid-list.
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        sent = self._cursor_value
        next_token = response.headers.get(self.header_name) or None
        if not next_token or next_token == sent:
            self._has_next_page = False
        else:
            self._cursor_value = next_token
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_token": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_token = state.get("next_token")
        if next_token is not None:
            self._cursor_value = next_token
            self._has_next_page = True


def e2b_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[E2BResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = E2B_ENDPOINTS[endpoint]

    # One tracked session reused across every page so urllib3 keeps the connection alive.
    # `redact_values` masks the key from tracked HTTP samples (the `X-API-Key` header isn't on the
    # generic scrubber's denylist); `allow_redirects=False` keeps it from replaying to another host;
    # `capture=False` keeps raw response bodies (which can hold secret-bearing sandbox metadata the
    # name-based scrubbers miss) out of sample storage, since `_scrub` only runs after capture.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": E2B_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Auth via the framework so the key is injected per-request and redacted from logs.
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
            "paginator": HeaderCursorPaginator(),
            "session": session,
            # Same-host-only (base_url host is implicitly allowed) + no redirects: an off-host
            # pagination/resume URL or a 3xx can't replay the API key to another origin.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": E2B_PAGE_LIMIT},
                    # E2B list endpoints return a bare JSON array. Require a list so a wrapped/error
                    # body (a response-shape change) fails loud instead of syncing the object as a row.
                    "data_selector_required": True,
                },
                # Drop secret-bearing sandbox metadata before ingesting.
                "data_map": _scrub,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_token is not None:
            initial_paginator_state = {"next_token": resume.next_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_token") is not None:
            resumable_source_manager.save_state(E2BResumeConfig(next_token=state["next_token"]))

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
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # Cheapest authenticated probe: list a single sandbox. 200 means the team-scoped key is genuine,
    # 401/403 means it isn't. Anything else — a timeout, connection error, rate limit, or 5xx — is a
    # transient upstream problem that says nothing about the key, so raise rather than mislabel a valid
    # key "invalid" and send the user down the wrong recovery path.
    # `redact_values` masks the key from tracked HTTP samples (the `X-API-Key` header isn't on the
    # generic scrubber's denylist); `allow_redirects=False` keeps the key from replaying to another host;
    # `capture=False` keeps the raw response body out of sample storage, since a sandbox's user-set
    # metadata can carry secrets the name-based scrubbers can't recognise (see `SENSITIVE_FIELDS`).
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False),
        f"{E2B_BASE_URL}/v2/sandboxes?limit=1",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
    )
    if ok:
        return True
    if status in (401, 403):
        return False
    raise E2BRetryableError(f"E2B credential probe failed (retryable): status={status}")
