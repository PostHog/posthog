from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

# Documented default and maximum for the v2 `limit` param.
PAGE_SIZE = 100

DemodeskApiVersion = Literal["v1", "v2"]


@dataclass(frozen=True)
class DemodeskEndpointConfig:
    name: str
    path: str
    # Demodesk keeps two API surfaces live: v2 (recommended; recordings, users) and the legacy v1
    # (meetings). They differ in auth scheme and pagination, so each endpoint declares its surface.
    api_version: DemodeskApiVersion
    primary_keys: list[str]
    partition_key: str | None = None
    # v1 responses are JSON:API shaped ({"id", "type", "attributes": {...}}); flatten `attributes`
    # into the row root so columns are queryable directly.
    flatten_json_api: bool = False
    params: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Ransack query param carrying the server-side floor for each advertised incremental field.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    default_incremental_field: str | None = None
    sort_mode: SortMode = "asc"
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None


DEMODESK_ENDPOINTS: dict[str, DemodeskEndpointConfig] = {
    "demos": DemodeskEndpointConfig(
        name="demos",
        path="/v1/demos",
        api_version="v1",
        primary_keys=["id"],
        partition_key="createdAt",
        flatten_json_api=True,
        # Without this filter the listing only covers meetings of the API key's own user.
        params={"filter[all_team_members_dashboard]": "true"},
        # Full refresh only: the v1 listing filters on `start_date` (the scheduled time, which a
        # reschedule can move backwards) and exposes no creation/update timestamp filter, so a
        # watermark sync could permanently skip rows.
    ),
    "demo_templates": DemodeskEndpointConfig(
        name="demo_templates",
        path="/v1/demo_templates",
        api_version="v1",
        primary_keys=["id"],
        flatten_json_api=True,
    ),
    "users": DemodeskEndpointConfig(
        name="users",
        path="/v2/users",
        api_version="v2",
        primary_keys=["id"],
    ),
    "recordings": DemodeskEndpointConfig(
        name="recordings",
        path="/v2/recordings",
        api_version="v2",
        primary_keys=["recordingId"],
        partition_key="createdAt",
        incremental_fields=[
            incremental_field("updatedAt"),
            incremental_field("createdAt"),
        ],
        incremental_param_by_field={
            "updatedAt": "filter[updated_at_gteq]",
            "createdAt": "filter[created_at_gteq]",
        },
        default_incremental_field="updatedAt",
        # The v2 cursor pagination documents no ordering guarantee, so the watermark must only be
        # committed after a complete pass; "desc" is what makes the pipeline defer that commit.
        sort_mode="desc",
    ),
    "recording_summaries": DemodeskEndpointConfig(
        name="recording_summaries",
        path="/v2/recordings/{recording_token}/summaries",
        api_version="v2",
        # Summary ids are not documented as globally unique, so the parent token is part of the key.
        primary_keys=["recordingToken", "summaryId"],
        partition_key="createdAt",
        fanout=DependentEndpointConfig(
            parent_name="recordings",
            resolve_param="recording_token",
            resolve_field="recordingToken",
            include_from_parent=["recordingToken"],
            parent_field_renames={"recordingToken": "recordingToken"},
            # A recording deleted between the parent listing and this child fetch 404s; treat it
            # as an empty child instead of failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "recording_scorecards": DemodeskEndpointConfig(
        name="recording_scorecards",
        path="/v2/recordings/{recording_token}/scorecards",
        api_version="v2",
        primary_keys=["recordingToken", "scorecardId"],
        partition_key="createdAt",
        fanout=DependentEndpointConfig(
            parent_name="recordings",
            resolve_param="recording_token",
            resolve_field="recordingToken",
            include_from_parent=["recordingToken"],
            parent_field_renames={"recordingToken": "recordingToken"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(DEMODESK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DEMODESK_ENDPOINTS.items() if config.incremental_fields
}
