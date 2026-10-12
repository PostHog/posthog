from dataclasses import dataclass, field
from typing import Optional

# n8n's public REST API is served per-instance under this base path.
N8N_API_PATH = "/api/v1"

# Cursor pagination page size. The API defaults to 100 and caps at 250; we
# request the max to minimize round trips on large instances.
PAGE_SIZE = 250


@dataclass
class N8nEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field used for datetime partitioning. n8n objects that
    # carry no timestamp (variables, projects) leave this None and go unpartitioned.
    partition_key: Optional[str] = None
    # Extra query params sent on every list request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)


N8N_ENDPOINTS: dict[str, N8nEndpointConfig] = {
    # Workflows carry createdAt/updatedAt. `excludePinnedData` keeps the
    # dev-time pinned sample payloads out of each row.
    "workflows": N8nEndpointConfig(
        name="workflows",
        path="/workflows",
        partition_key="createdAt",
        extra_params={"excludePinnedData": "true"},
    ),
    # Executions have no createdAt/updatedAt; startedAt is the stable creation
    # timestamp. The heavy per-run `data` blob is omitted (includeData defaults
    # to false) to keep rows small.
    "executions": N8nEndpointConfig(
        name="executions",
        path="/executions",
        partition_key="startedAt",
    ),
    "tags": N8nEndpointConfig(
        name="tags",
        path="/tags",
        partition_key="createdAt",
    ),
    "users": N8nEndpointConfig(
        name="users",
        path="/users",
        partition_key="createdAt",
    ),
    # Variables and projects expose no timestamp field, so they are full refresh
    # only with no datetime partitioning.
    "variables": N8nEndpointConfig(
        name="variables",
        path="/variables",
    ),
    "projects": N8nEndpointConfig(
        name="projects",
        path="/projects",
    ),
}

ENDPOINTS = tuple(N8N_ENDPOINTS.keys())
