from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Cursor pagination: `limit` maxes out at 100 on every paginated E2B list endpoint. It is also the
# cap on how many sandbox ids `/sandboxes/metrics` accepts per call, so one page of sandboxes
# costs exactly one batched metrics request.
E2B_PAGE_LIMIT = 100


@frozen
class E2BEndpointConfig:
    name: str
    path: str
    # Field to partition by. Must be a STABLE creation-style timestamp so partitions don't
    # rewrite on every sync; `None` for endpoints whose rows carry no timestamp.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Key the rows sit under in the response body; `None` for a bare JSON array.
    data_selector: Optional[str] = None
    # `None` for endpoints that document no page-size param — sending one risks a strict validator
    # rejecting the request.
    page_size_param: Optional[str] = "limit"
    page_size: int = E2B_PAGE_LIMIT
    fanout: Optional[DependentEndpointConfig] = None
    # The path carries `{team_id}`, which only the user can supply (see the source's `team_id` field).
    requires_team_id: bool = False
    # Read by the shared fan-out helper's `FanoutEndpointLike` protocol. No E2B endpoint filters
    # server-side by timestamp in a way we can drive a cursor from, so both stay empty.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Every sandbox-level endpoint hangs off `/sandboxes/{sandboxID}/...`, so the sandbox list is the
# parent they resolve from. `/sandboxes/{sandboxID}/metrics` documents no page-size param, so the
# parent carries its own `limit` instead of the shared one.
SANDBOX_FANOUT = DependentEndpointConfig(
    parent_name="sandboxes",
    resolve_param="sandboxID",
    resolve_field="sandboxID",
    include_from_parent=["sandboxID"],
    parent_field_renames={"sandboxID": "sandboxID"},
    parent_params={"limit": E2B_PAGE_LIMIT},
)

TEMPLATE_FANOUT = DependentEndpointConfig(
    parent_name="templates",
    resolve_param="templateID",
    resolve_field="templateID",
    include_from_parent=["templateID"],
    parent_field_renames={"templateID": "templateID"},
)


# E2B's list endpoints are point-in-time inventories reachable with a team-scoped API key. None of
# them expose a server-side timestamp filter we can safely drive a cursor from, so every endpoint is
# full refresh (see the source's `get_schemas`). Cursor pagination (`nextToken` request param +
# `X-Next-Token` response header) lets a single run resume mid-list after a heartbeat timeout
# without restarting.
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
    # GET /sandboxes/{sandboxID}/metrics — the CPU/memory/disk series for one sandbox. Off by
    # default: it costs one request per sandbox per sync, which `sandbox_metrics_latest` avoids
    # for teams that only want current usage.
    "sandbox_metrics": E2BEndpointConfig(
        name="sandbox_metrics",
        path="/sandboxes/{sandboxID}/metrics",
        partition_key="timestamp",
        primary_keys=["sandboxID", "timestampUnix"],
        page_size_param=None,
        fanout=SANDBOX_FANOUT,
        should_sync_default=False,
    ),
    # GET /sandboxes/metrics — the latest sample for up to 100 sandboxes per call. One row per
    # sandbox, so the only key is the sandbox id; the sample timestamp moves every sync, which
    # rules it out as a partition key.
    "sandbox_metrics_latest": E2BEndpointConfig(
        name="sandbox_metrics_latest",
        path="/sandboxes/metrics",
        primary_keys=["sandboxID"],
        page_size_param=None,
    ),
    # GET /templates/{templateID} — the build history of one template, under a `builds` key.
    "template_builds": E2BEndpointConfig(
        name="template_builds",
        path="/templates/{templateID}",
        partition_key="createdAt",
        primary_keys=["templateID", "buildID"],
        data_selector="builds",
        fanout=TEMPLATE_FANOUT,
    ),
    # GET /teams/{teamID}/metrics — concurrent sandboxes and sandbox start rate over time.
    "team_metrics": E2BEndpointConfig(
        name="team_metrics",
        path="/teams/{team_id}/metrics",
        partition_key="timestamp",
        primary_keys=["timestampUnix"],
        page_size_param=None,
        requires_team_id=True,
    ),
}

ENDPOINTS = tuple(E2B_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter, so none is incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
