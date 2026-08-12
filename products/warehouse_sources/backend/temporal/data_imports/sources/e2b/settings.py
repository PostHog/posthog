from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class E2BEndpointConfig:
    name: str
    path: str
    # Field to partition by. Must be a STABLE creation-style timestamp so partitions don't
    # rewrite on every sync; `None` for endpoints whose rows carry no timestamp.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# E2B's list endpoints are point-in-time inventories reachable with a team-scoped API key. None of
# them expose a server-side timestamp filter, so every endpoint is full refresh (see the source's
# `get_schemas`). Cursor pagination (`nextToken` request param + `X-Next-Token` response header) lets
# a single run resume mid-list after a heartbeat timeout without restarting.
E2B_ENDPOINTS: dict[str, E2BEndpointConfig] = {
    # GET /v2/sandboxes — running and paused sandboxes. Terminated sandboxes are not listed here.
    "sandboxes": E2BEndpointConfig(
        name="sandboxes",
        path="/v2/sandboxes",
        partition_key="startedAt",
        primary_keys=["sandboxID"],
    ),
    # GET /v2/templates — the team's sandbox templates.
    "templates": E2BEndpointConfig(
        name="templates",
        path="/v2/templates",
        partition_key="createdAt",
        primary_keys=["templateID"],
    ),
    # GET /snapshots — paused-sandbox snapshots for the team. `SnapshotInfo` carries no timestamp,
    # so there is no stable partition key.
    "snapshots": E2BEndpointConfig(
        name="snapshots",
        path="/snapshots",
        primary_keys=["snapshotID"],
    ),
}

ENDPOINTS = tuple(E2B_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter, so none is incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
