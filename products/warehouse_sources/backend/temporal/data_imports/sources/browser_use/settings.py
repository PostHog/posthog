from dataclasses import dataclass, field
from typing import Literal, Optional

# Field names, pagination params, and response envelopes below were taken from the Browser Use
# v3 OpenAPI spec (https://api.browser-use.com/api/v3/openapi.json) and confirmed against the
# live API. The v3 list endpoints expose no server-side created/updated-since filter and no sort
# parameter, so every endpoint syncs full-refresh only (see get_schemas) and no incremental cursor
# is declared. Partition keys use required, immutable creation-time fields so partitions never
# rewrite on later syncs.

PaginationStyle = Literal["page", "pageNumber", "cursor"]


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
