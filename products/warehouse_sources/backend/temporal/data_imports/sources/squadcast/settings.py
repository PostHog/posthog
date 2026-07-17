from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How each endpoint is iterated. Squadcast mixes several pagination styles across its API
# versions, so the transport dispatches on this instead of hardcoding per-endpoint branches:
# - "none": a single request returns the full list (no pagination params).
# - "offset": 0-based `offset`/`limit` params with a `meta.total` counter (SLOs).
# - "cursor": `pageSize`/`cursor` params with a `pageInfo.nextCursor` reference (v4 schedules).
# - "incident_export": required `start_time`/`end_time` window, chunked client-side (incidents).
# - "postmortems": required `fromDate`/`toDate`/`limit` window, single request per team.
PaginationStyle = Literal["none", "offset", "cursor", "incident_export", "postmortems"]


@dataclass
class SquadcastEndpointConfig:
    path: str  # Path under the regional API base URL, e.g. "/v3/services"
    pagination: PaginationStyle = "none"
    # Query param carrying the team id for team-scoped endpoints ("owner_id" on v3,
    # "teamID" on v4). None means the endpoint is org-level and needs no fan-out.
    team_param: Optional[str] = None
    # Keys to walk in the response body to reach the list of rows.
    envelope: tuple[str, ...] = ("data",)
    primary_key: str = "id"
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


SQUADCAST_ENDPOINTS: dict[str, SquadcastEndpointConfig] = {
    "incidents": SquadcastEndpointConfig(
        # The API has no plain incident list endpoint; the JSON export is the documented way to
        # pull incidents in bulk. Its required `start_time`/`end_time` filters key on creation
        # time, which gives us a genuine server-side incremental window. Status changes to
        # incidents created before the cursor are only picked up by a full refresh.
        path="/v3/incidents/export",
        pagination="incident_export",
        team_param="owner_id",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "postmortems": SquadcastEndpointConfig(
        path="/v3/incidents/postmortem",
        pagination="postmortems",
        team_param="owner_id",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "services": SquadcastEndpointConfig(
        path="/v3/services",
        team_param="owner_id",
    ),
    "escalation_policies": SquadcastEndpointConfig(
        # The endpoint documents optional `page_number`/`page_size` params, but their base
        # (0 vs 1) is undocumented and per-team policy counts are small, so we make a single
        # unpaginated request and warn if `meta.total_count` reports more rows than returned.
        path="/v3/escalation-policies",
        team_param="owner_id",
    ),
    "schedules": SquadcastEndpointConfig(
        path="/v4/schedules",
        pagination="cursor",
        team_param="teamID",
    ),
    "runbooks": SquadcastEndpointConfig(
        path="/v3/runbooks",
        team_param="owner_id",
    ),
    "slos": SquadcastEndpointConfig(
        path="/v3/slo",
        pagination="offset",
        team_param="owner_id",
        envelope=("data", "slos"),
    ),
    "users": SquadcastEndpointConfig(
        path="/v3/users",
    ),
    "teams": SquadcastEndpointConfig(
        path="/v3/teams",
    ),
}

ENDPOINTS = tuple(SQUADCAST_ENDPOINTS.keys())
