from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Harvest embeds the API version as the first path segment (`/v1/candidates`, `/v3/candidates`).
GREENHOUSE_V1 = "v1"
GREENHOUSE_V3 = "v3"


@dataclass
class GreenhouseEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field used for datetime partitioning. Must never be a field that mutates over an
    # object's lifetime (so `created_at`, never `updated_at`). Left as ``None`` for the small
    # reference endpoints whose objects don't expose a creation timestamp.
    partition_key: Optional[str] = None
    # Maps an advertised incremental field name to the Harvest v1 query param that filters it
    # server-side (e.g. `updated_at` -> `updated_after`). Only populated for endpoints with a
    # genuine documented server-side timestamp filter. v3 filters on the field name itself, so
    # it needs no mapping.
    incremental_filter_params: dict[str, str] = field(default_factory=dict)
    # Harvest v3 path, where v3 renamed the collection. ``None`` means v3 kept the v1 name.
    v3_path: Optional[str] = None

    def path_for_version(self, api_version: str) -> str:
        if api_version == GREENHOUSE_V3 and self.v3_path is not None:
            return self.v3_path
        return self.path


def _datetime_incremental_field(name: str) -> IncrementalField:
    # Harvest returns timestamps as ISO 8601 strings (e.g. "2019-01-01T00:00:00.000Z"), so the
    # cursor is stored and compared as a datetime — no normalization needed on the rows.
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Core Greenhouse Harvest (recruiting) objects. The major streams expose documented
# `updated_after` / `created_after` server-side filters and ship incremental; the small
# reference endpoints (departments, offices, sources, rejection/close reasons) have no
# timestamp filter and ship full refresh. Per-parent fan-out streams (activity feeds,
# per-application interviews/scorecards) are intentionally deferred to a later pass.
GREENHOUSE_ENDPOINTS: dict[str, GreenhouseEndpointConfig] = {
    "candidates": GreenhouseEndpointConfig(
        name="candidates",
        path="/candidates",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "applications": GreenhouseEndpointConfig(
        name="applications",
        path="/applications",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("last_activity_at"),
            _datetime_incremental_field("created_at"),
        ],
        # `/applications` does not document `updated_after`; it exposes `last_activity_after`
        # (filters `last_activity_at`) and `created_after` instead.
        incremental_filter_params={
            "last_activity_at": "last_activity_after",
            "created_at": "created_after",
        },
    ),
    "jobs": GreenhouseEndpointConfig(
        name="jobs",
        path="/jobs",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "job_posts": GreenhouseEndpointConfig(
        name="job_posts",
        path="/job_posts",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "offers": GreenhouseEndpointConfig(
        name="offers",
        path="/offers",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "scorecards": GreenhouseEndpointConfig(
        name="scorecards",
        path="/scorecards",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "scheduled_interviews": GreenhouseEndpointConfig(
        name="scheduled_interviews",
        path="/scheduled_interviews",
        # v3 renamed this collection to `interviews`. The schema (and so the warehouse table) keeps
        # its v1 name so the table set is identical on both versions and a repin can't orphan a table.
        v3_path="/interviews",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "users": GreenhouseEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        incremental_filter_params={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
    ),
    "departments": GreenhouseEndpointConfig(
        name="departments",
        path="/departments",
        primary_keys=["id"],
    ),
    "offices": GreenhouseEndpointConfig(
        name="offices",
        path="/offices",
        primary_keys=["id"],
    ),
    "sources": GreenhouseEndpointConfig(
        name="sources",
        path="/sources",
        primary_keys=["id"],
    ),
    "rejection_reasons": GreenhouseEndpointConfig(
        name="rejection_reasons",
        path="/rejection_reasons",
        primary_keys=["id"],
    ),
    "close_reasons": GreenhouseEndpointConfig(
        name="close_reasons",
        path="/close_reasons",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(GREENHOUSE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GREENHOUSE_ENDPOINTS.items()
}
