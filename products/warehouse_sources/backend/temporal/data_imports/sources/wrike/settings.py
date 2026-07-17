from dataclasses import dataclass
from typing import Optional


@dataclass
class WrikeEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # Stable creation-time field used for datetime partitioning. Only set where the resource
    # exposes an immutable creation timestamp — never an `updatedDate`-style field, which would
    # rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Wrike paginates a small number of large list endpoints (`/tasks`, `/comments`,
    # `/audit_log`) via `pageSize` + `nextPageToken`. Most endpoints (folders, contacts,
    # workflows, custom fields, spaces) return the full result set in a single response with no
    # pagination token, so we fetch them in one request.
    paginated: bool = False


# Wrike's REST API (v4) does not expose a server-side cursor/timestamp filter we can reliably
# map onto an incremental watermark without live verification: only a handful of endpoints accept
# an `updatedDate` range and combining it with `nextPageToken` paging and the 1000-row page cap
# has ordering edge cases we can't confirm without credentials. We therefore ship every endpoint
# as full refresh (matching Airbyte's Wrike connector); incremental sync can be layered on later
# once the `updatedDate` filter is curl-verified against the live API.
WRIKE_ENDPOINTS: dict[str, WrikeEndpointConfig] = {
    "tasks": WrikeEndpointConfig(
        name="tasks",
        path="/tasks",
        partition_key="createdDate",
        paginated=True,
    ),
    "folders": WrikeEndpointConfig(
        name="folders",
        path="/folders",
    ),
    "contacts": WrikeEndpointConfig(
        name="contacts",
        path="/contacts",
    ),
    "workflows": WrikeEndpointConfig(
        name="workflows",
        path="/workflows",
    ),
    "custom_fields": WrikeEndpointConfig(
        name="custom_fields",
        path="/customfields",
    ),
    "spaces": WrikeEndpointConfig(
        name="spaces",
        path="/spaces",
    ),
}

ENDPOINTS = tuple(WRIKE_ENDPOINTS.keys())
