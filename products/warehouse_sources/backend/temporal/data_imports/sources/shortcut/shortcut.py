import logging
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    SHORTCUT_ENDPOINTS,
    ShortcutEndpointConfig,
)

logger = logging.getLogger(__name__)

SHORTCUT_BASE_URL = "https://api.app.shortcut.com/api/v3"

# `POST /stories/search` returns nothing for an empty body, so full refresh and the first
# incremental run send this created_at floor to match every story. It doubles as the lower
# bound the paginator advances to page past the result cap.
STORY_SEARCH_EPOCH_START = "1970-01-01T00:00:00Z"

# `POST /stories/search` returns a bare array with no pagination and caps each response. A full
# response means more may exist, so the paginator refetches with a higher created_at floor.
STORY_SEARCH_RESULT_CAP = 1000


def _base_headers() -> dict[str, str]:
    # The Shortcut-Token credential is supplied via the framework api_key auth (location="header"),
    # so its value is redacted from logs and raised errors; only the non-secret content headers here.
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for Shortcut's `*_start` search filters (RFC 3339)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_search_body(
    config: ShortcutEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the JSON body for `POST /stories/search`.

    Maps the user-selected incremental field to the matching server-side filter param, and
    always sets a created_at floor so the body is never empty — an empty body makes the
    endpoint return zero stories on full refresh and the first incremental run.
    """
    body: dict[str, Any] = {}
    # GET list endpoints carry no request body.
    if config.method != "POST":
        return body
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        field_name = incremental_field or "updated_at"
        param = config.incremental_params.get(field_name)
        if param:
            body[param] = _format_incremental_value(db_incremental_field_last_value)
    # An epoch floor matches every story; a real created_at cursor above overrides it.
    body.setdefault("created_at_start", STORY_SEARCH_EPOCH_START)
    return body


class StoriesSearchPaginator(BasePaginator):
    """Page `POST /stories/search` past its result cap by advancing the created_at floor.

    The endpoint returns a bare array with no pagination and caps each response at
    `STORY_SEARCH_RESULT_CAP`. When a response is full, more stories may exist, so advance
    `created_at_start` to the newest created_at seen and refetch; merge dedup on `id` drops
    the boundary stories re-read at the floor. Stop when a response is under the cap, or when
    the floor cannot advance because every story in a full page shares one created_at. This
    relies on the endpoint returning stories in created_at order, its established behavior.
    """

    def __init__(self, cap: int = STORY_SEARCH_RESULT_CAP) -> None:
        super().__init__()
        self._cap = cap
        self._next_created_at_start: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        if len(rows) < self._cap:
            self._has_next_page = False
            return
        newest = max((row.get("created_at") for row in rows if row.get("created_at")), default=None)
        if newest is None or newest == self._next_created_at_start:
            logger.warning(
                "Shortcut stories/search hit its %s-row cap without a way to page further; some stories may be missing",
                self._cap,
            )
            self._has_next_page = False
            return
        self._next_created_at_start = newest
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._next_created_at_start is not None:
            if request.json is None:
                request.json = {}
            request.json["created_at_start"] = self._next_created_at_start


def shortcut_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SHORTCUT_ENDPOINTS[endpoint]

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "method": config.method,
        # Every Shortcut list endpoint (and stories/search) returns a bare JSON array; require it to
        # be a list so a changed/error 200 body fails loud instead of syncing a stray object as a row.
        "data_selector_required": True,
    }
    if config.method == "POST":
        # Shortcut's stories/search carries its server-side timestamp filters in the POST body (not the
        # query string). This seeds the first page; the paginator advances created_at_start for later pages.
        endpoint_config["json"] = _build_search_body(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHORTCUT_BASE_URL,
            "headers": _base_headers(),
            "auth": {
                "type": "api_key",
                "api_key": api_token,
                "name": "Shortcut-Token",
                "location": "header",
            },
            # Flat list endpoints return the whole collection in one response; stories/search
            # caps each response, so it pages by advancing the created_at floor.
            "paginator": StoriesSearchPaginator() if config.method == "POST" else SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            cast(
                "EndpointResource",
                {
                    "name": endpoint,
                    "endpoint": endpoint_config,
                },
            )
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Probe the cheapest authenticated endpoint to confirm the token is genuine."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{SHORTCUT_BASE_URL}/member",
        headers={"Shortcut-Token": api_token, **_base_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Shortcut API token. Generate a new token in Settings > API Tokens and reconnect."
    if status == 403:
        return False, "Your Shortcut API token does not have access to this workspace. Please check its permissions."
    return False, f"Shortcut API returned an unexpected status: {status}"
