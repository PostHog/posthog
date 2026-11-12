from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

SMARTREACH_API_V1 = "v1"
SMARTREACH_API_V3 = "v3"


@dataclass(frozen=False)
class SmartreachEndpointConfig:
    name: str
    path: str
    # SmartReach nests the row list inside the `data` object under a per-endpoint key
    # (e.g. `data.prospects`, `data.campaigns`), so each endpoint records which key to read.
    # None means the whole response body is the row (a single object, e.g. campaign stats).
    data_key: Optional[str]
    # SmartReach object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable (never-rewritten) datetime field to partition by. Only set where the object
    # exposes a genuine creation timestamp — never an "updated" field, which changes on edit.
    partition_key: Optional[str] = None
    # v3 rejects a team-level request without the `team_id` query param. `/teams` lists the
    # teams the key can see, so it takes none.
    team_scoped: bool = True
    # The endpoints added after the v1 catalog exist only in the v3 reference.
    api_versions: tuple[str, ...] = (SMARTREACH_API_V1, SMARTREACH_API_V3)
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the fan-out helper. SmartReach takes no page-size param and no endpoint syncs
    # incrementally.
    page_size: int = 0
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


def _campaign_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="campaigns",
        resolve_param="campaign_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "campaign_id"},
    )


# SmartReach list endpoints. All are full-refresh only: while several endpoints expose
# `newer_than`/`older_than` epoch filters, we ship full refresh to avoid depending on ordering we
# cannot verify (see the implementing-warehouse-sources skill).
SMARTREACH_ENDPOINTS: dict[str, SmartreachEndpointConfig] = {
    "prospects": SmartreachEndpointConfig(name="prospects", path="/prospects", data_key="prospects"),
    "campaigns": SmartreachEndpointConfig(name="campaigns", path="/campaigns", data_key="campaigns"),
    "campaign_prospects": SmartreachEndpointConfig(
        name="campaign_prospects",
        path="/campaigns/{campaign_id}/prospects",
        data_key="campaign_prospects",
        # A prospect can be in several campaigns, so the membership row is keyed on both ids.
        primary_keys=["campaign_id", "prospect_id"],
        api_versions=(SMARTREACH_API_V3,),
        fanout=_campaign_fanout(),
    ),
    "campaign_stats": SmartreachEndpointConfig(
        name="campaign_stats",
        path="/campaigns/{campaign_id}/stats",
        data_key=None,
        primary_keys=["campaign_id"],
        api_versions=(SMARTREACH_API_V3,),
        fanout=_campaign_fanout(),
    ),
    "teams": SmartreachEndpointConfig(
        name="teams",
        path="/teams",
        data_key="teams",
        team_scoped=False,
        api_versions=(SMARTREACH_API_V3,),
    ),
    "users": SmartreachEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        api_versions=(SMARTREACH_API_V3,),
    ),
}

ENDPOINTS = tuple(SMARTREACH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
