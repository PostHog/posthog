from dataclasses import dataclass, field
from typing import Literal, Optional

# Field names, pagination params, and response envelopes below were taken from the Browser Use
# v3 and v4 OpenAPI specs (https://api.browser-use.com/api/v3/openapi.json,
# https://api.browser-use.com/api/v4/openapi.json) and confirmed against the live API. No list
# endpoint in either version exposes a server-side created/updated-since filter or a sort
# parameter, so every endpoint syncs full-refresh only (see get_schemas) and no incremental cursor
# is declared. Partition keys use required, immutable creation-time fields so partitions never
# rewrite on later syncs.

# Vendor API versions. The version is a URL path segment (`/api/<version>`), so it is also the
# request layer's version constant. v3 was the experimental agent API; v4 is the current default.
BROWSER_USE_API_VERSION_V3 = "v3"
BROWSER_USE_API_VERSION_V4 = "v4"

# "page"/"pageNumber" -> 1-indexed offset paging with a total-items count.
# "cursor" -> `after=<last row id>` + `hasMore` flag (v3 GET /sessions/{id}/messages).
# "keyset" -> `cursor=<opaque token>` + `limit`, with `nextCursor`/`hasMore` in the body
#   (v4 GET /sessions and GET /runs — v4 dropped the offset+count model for scale).
PaginationStyle = Literal["page", "pageNumber", "cursor", "keyset"]


@dataclass
class BrowserUseEndpointConfig:
    name: str
    path: str
    # Key in the JSON response body that holds the array of rows.
    data_key: str
    # "page" -> 1-indexed page + page_size (GET /sessions)
    # "pageNumber" -> 1-indexed pageNumber + pageSize (GET /browsers, /profiles, /workspaces)
    # "cursor" -> after=<uuid> + limit, with a hasMore flag (GET /sessions/{id}/messages)
    pagination: PaginationStyle
    # Every list endpoint caps the page size at 100.
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable creation-time field to partition by; None disables partitioning for the endpoint.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # When True, `path` is a template with a `{session_id}` placeholder and rows are gathered by
    # fanning out one paginated request per agent session.
    fan_out_over_sessions: bool = False


BROWSER_USE_ENDPOINTS: dict[str, BrowserUseEndpointConfig] = {
    "sessions": BrowserUseEndpointConfig(
        name="sessions",
        path="/sessions",
        data_key="sessions",
        pagination="page",
        partition_key="createdAt",
    ),
    "browser_sessions": BrowserUseEndpointConfig(
        name="browser_sessions",
        path="/browsers",
        data_key="items",
        pagination="pageNumber",
        partition_key="startedAt",
    ),
    "profiles": BrowserUseEndpointConfig(
        name="profiles",
        path="/profiles",
        data_key="items",
        pagination="pageNumber",
        partition_key="createdAt",
    ),
    "workspaces": BrowserUseEndpointConfig(
        name="workspaces",
        path="/workspaces",
        data_key="items",
        pagination="pageNumber",
        partition_key="createdAt",
    ),
    # Per-session agent steps. Fans out one cursor-paginated request per session, so it's opt-in
    # (off by default) to avoid the extra API cost when a user only wants session-level data. The
    # message id is a UUID, but the parent session id is kept in the composite key so a duplicated
    # id can never collapse rows across sessions.
    "session_messages": BrowserUseEndpointConfig(
        name="session_messages",
        path="/sessions/{session_id}/messages",
        data_key="messages",
        pagination="cursor",
        primary_keys=["sessionId", "id"],
        partition_key="createdAt",
        should_sync_default=False,
        fan_out_over_sessions=True,
    ),
}

ENDPOINTS = tuple(BROWSER_USE_ENDPOINTS.keys())

# v4 reshapes what v3 served. `GET /sessions` moved to keyset pagination and is now a slim
# container (the per-run model/token/cost fields moved onto the new `GET /runs` resource, synced
# here as the `runs` table). `GET /browsers` and `GET /profiles` are unchanged from v3. Two v3
# resources have no v4 list endpoint and so are absent here: the `GET /workspaces` list (v4 only
# exposes a single-workspace GET) and `GET /sessions/{id}/messages` (removed entirely). The table
# name set therefore differs from v3 by design — a v4-pinned source discovers only what v4 serves.
BROWSER_USE_ENDPOINTS_V4: dict[str, BrowserUseEndpointConfig] = {
    "sessions": BrowserUseEndpointConfig(
        name="sessions",
        path="/sessions",
        data_key="sessions",
        pagination="keyset",
        primary_keys=["sessionId"],
        partition_key="createdAt",
    ),
    # Agent runs — status, model, token usage, and per-run cost. Carries the fields v3 kept on
    # `sessions`, so it stays on by default to preserve that data for new sources.
    "runs": BrowserUseEndpointConfig(
        name="runs",
        path="/runs",
        data_key="runs",
        pagination="keyset",
        partition_key="createdAt",
    ),
    "browser_sessions": BrowserUseEndpointConfig(
        name="browser_sessions",
        path="/browsers",
        data_key="items",
        pagination="pageNumber",
        partition_key="startedAt",
    ),
    "profiles": BrowserUseEndpointConfig(
        name="profiles",
        path="/profiles",
        data_key="items",
        pagination="pageNumber",
        partition_key="createdAt",
    ),
}

ENDPOINTS_BY_VERSION: dict[str, dict[str, BrowserUseEndpointConfig]] = {
    BROWSER_USE_API_VERSION_V3: BROWSER_USE_ENDPOINTS,
    BROWSER_USE_API_VERSION_V4: BROWSER_USE_ENDPOINTS_V4,
}


def endpoints_for_version(api_version: str) -> dict[str, BrowserUseEndpointConfig]:
    try:
        return ENDPOINTS_BY_VERSION[api_version]
    except KeyError as e:
        raise ValueError(f"Unsupported Browser Use API version: {api_version!r}") from e
