from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class LeverEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field used for datetime partitioning. Must never be a field that mutates
    # over an object's lifetime (so `createdAt`, never `updatedAt`).
    partition_key: Optional[str] = None
    # Maps an advertised incremental field name to the Lever query param that filters it
    # server-side (e.g. `updatedAt` -> `updated_at_start`). Only populated for endpoints
    # with a genuine server-side timestamp filter.
    incremental_filter_params: dict[str, str] = field(default_factory=dict)
    page_size: int = 100  # Lever default and maximum is 100
    default_incremental_field: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    # Rows live in this array field of each listed object rather than at the top level of `data`.
    nested_rows_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


def _timestamp_incremental_field(name: str) -> IncrementalField:
    # Lever returns timestamps as Unix-epoch milliseconds. We normalize them to epoch
    # seconds (stored as integers), matching the convention used by the other epoch-based
    # sources (Clerk, Stripe) so datetime partitioning and incremental watermarks line up.
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


def _opportunity_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="opportunities",
        resolve_param="opportunity_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "opportunity_id"},
        # The child only needs each opportunity's id, so skip the rest of the payload.
        parent_params={"include": "id"},
        # An opportunity deleted between the listing and its child fetch 404s.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


# Only `opportunities` exposes documented server-side timestamp filters
# (`created_at_start` / `updated_at_start`), so it is the only endpoint shipped with
# incremental sync. Everything else is full refresh. The per-opportunity children have no
# timestamp filter, and the opportunity `updated_at` filter does not track changes to them,
# so they fan out over every opportunity on each sync.
LEVER_ENDPOINTS: dict[str, LeverEndpointConfig] = {
    "opportunities": LeverEndpointConfig(
        name="opportunities",
        path="/opportunities",
        primary_keys=["id"],
        partition_key="createdAt",
        incremental_fields=[
            _timestamp_incremental_field("createdAt"),
            _timestamp_incremental_field("updatedAt"),
        ],
        incremental_filter_params={
            "createdAt": "created_at_start",
            "updatedAt": "updated_at_start",
        },
    ),
    # The per-opportunity applications endpoint is deprecated; Lever points to listing
    # opportunities with `expand=applications` instead. Each opportunity has at most one.
    "applications": LeverEndpointConfig(
        name="applications",
        path="/opportunities",
        primary_keys=["id"],
        partition_key="createdAt",
        params={"expand": "applications", "include": "applications"},
        nested_rows_field="applications",
    ),
    "offers": LeverEndpointConfig(
        name="offers",
        path="/opportunities/{opportunity_id}/offers",
        primary_keys=["opportunity_id", "id"],
        partition_key="createdAt",
        fanout=_opportunity_fanout(),
    ),
    "interviews": LeverEndpointConfig(
        name="interviews",
        path="/opportunities/{opportunity_id}/interviews",
        primary_keys=["opportunity_id", "id"],
        partition_key="createdAt",
        fanout=_opportunity_fanout(),
    ),
    "feedback": LeverEndpointConfig(
        name="feedback",
        path="/opportunities/{opportunity_id}/feedback",
        primary_keys=["opportunity_id", "id"],
        partition_key="createdAt",
        fanout=_opportunity_fanout(),
    ),
    "postings": LeverEndpointConfig(
        name="postings",
        path="/postings",
        primary_keys=["id"],
        partition_key="createdAt",
    ),
    "users": LeverEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["id"],
        partition_key="createdAt",
    ),
    "requisitions": LeverEndpointConfig(
        name="requisitions",
        path="/requisitions",
        primary_keys=["id"],
        partition_key="createdAt",
    ),
    "archive_reasons": LeverEndpointConfig(
        name="archive_reasons",
        path="/archive_reasons",
        primary_keys=["id"],
    ),
    "stages": LeverEndpointConfig(
        name="stages",
        path="/stages",
        primary_keys=["id"],
    ),
    # `/sources` and `/tags` return objects keyed by their unique `text` value (no `id`).
    "sources": LeverEndpointConfig(
        name="sources",
        path="/sources",
        primary_keys=["text"],
    ),
    "tags": LeverEndpointConfig(
        name="tags",
        path="/tags",
        primary_keys=["text"],
    ),
}

ENDPOINTS = tuple(LEVER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LEVER_ENDPOINTS.items()
}
