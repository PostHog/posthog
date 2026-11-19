from dataclasses import field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen, incremental_field

API_VERSION = "2026Q4"
BASE_URL = f"https://api.wise.com/{API_VERSION}"

# Transfers and activities change status for days after they are created, so an incremental run re-reads
# this window. It also covers rows created in one profile while the run read another profile.
INCREMENTAL_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

PaginationKind = Literal["single", "offset", "cursor"]


@frozen
class WiseEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    pagination: PaginationKind = "single"
    data_selector: str | None = None
    # The request param that carries the next cursor, and the response field that holds it.
    cursor_param: str | None = None
    cursor_path: str | None = None
    page_size: int = 100
    page_size_param: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # The request param that filters rows on the incremental field.
    incremental_param: str | None = None
    fanout: DependentEndpointConfig | None = None


PROFILE_FANOUT = DependentEndpointConfig(
    parent_name="profiles",
    resolve_param="profile_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "profileId"},
)

ENDPOINTS: dict[str, WiseEndpoint] = {
    "profiles": WiseEndpoint(
        name="profiles",
        path="/profiles",
        primary_keys=("id",),
        partition_key="createdAt",
    ),
    "balances": WiseEndpoint(
        name="balances",
        path="/profiles/{profile_id}/balances",
        primary_keys=("profileId", "id"),
        params={"types": "STANDARD,SAVINGS"},
        partition_key="creationTime",
        fanout=PROFILE_FANOUT,
    ),
    "transfers": WiseEndpoint(
        name="transfers",
        # `resolve` binds only path placeholders, so the profile filter sits in the path.
        path="/transfers?profile={profile_id}",
        primary_keys=("profileId", "id"),
        pagination="offset",
        page_size=100,
        page_size_param="limit",
        partition_key="created",
        incremental_fields=[incremental_field("created")],
        default_incremental_field="created",
        incremental_param="createdDateStart",
        fanout=PROFILE_FANOUT,
    ),
    "recipients": WiseEndpoint(
        name="recipients",
        path="/accounts?profileId={profile_id}",
        primary_keys=("profileId", "id"),
        pagination="cursor",
        data_selector="content",
        cursor_param="seekPosition",
        cursor_path="seekPositionForNext",
        page_size=20,
        page_size_param="size",
        fanout=PROFILE_FANOUT,
    ),
    "activities": WiseEndpoint(
        name="activities",
        path="/profiles/{profile_id}/activities",
        primary_keys=("profileId", "id"),
        pagination="cursor",
        data_selector="activities",
        cursor_param="nextCursor",
        cursor_path="cursor",
        page_size=100,
        page_size_param="size",
        partition_key="createdOn",
        incremental_fields=[incremental_field("createdOn")],
        default_incremental_field="createdOn",
        # `since` filters on a timestamp the docs do not name. A `createdOn` watermark is safe either way,
        # because an activity is always updated at or after its creation.
        incremental_param="since",
        fanout=PROFILE_FANOUT,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}

MERGE_ONLY_ENDPOINTS = tuple(INCREMENTAL_FIELDS)

INCREMENTAL_LOOKBACK = dict.fromkeys(INCREMENTAL_FIELDS, INCREMENTAL_LOOKBACK_SECONDS)
