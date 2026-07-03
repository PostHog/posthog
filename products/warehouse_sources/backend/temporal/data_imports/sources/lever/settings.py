from dataclasses import dataclass, field
from typing import Optional

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


# Only `opportunities` exposes documented server-side timestamp filters
# (`created_at_start` / `updated_at_start`), so it is the only endpoint shipped with
# incremental sync. Everything else is full refresh. Per-opportunity fan-out streams
# (interviews, feedback, offers, notes, referrals) and the descending-ordered
# `audit_events` stream are intentionally deferred — see source.py / the PR notes.
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
