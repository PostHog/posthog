from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BuildkiteEndpointConfig:
    name: str
    # Path template. ``{organization}`` is filled with the org slug from the source config.
    # Endpoints that aren't org-scoped (e.g. /v2/organizations) carry no placeholder.
    path: str
    incremental_fields: list[IncrementalField]
    # Field used to partition the Delta table. Must be STABLE (set once at creation) — never
    # ``updated_at`` style fields, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Maps an incremental field name to the Buildkite query param that filters on it server-side.
    # Only set for endpoints with a genuine server-side timestamp filter.
    incremental_param_map: Optional[dict[str, str]] = None


# Buildkite v2 REST API endpoints. Most resources are nested under an organization slug.
# Only the builds endpoint exposes a server-side timestamp filter (created_from), so it is the
# only one that supports incremental sync; the rest are full refresh.
BUILDKITE_ENDPOINTS: dict[str, BuildkiteEndpointConfig] = {
    "organizations": BuildkiteEndpointConfig(
        name="organizations",
        path="/v2/organizations",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "pipelines": BuildkiteEndpointConfig(
        name="pipelines",
        path="/v2/organizations/{organization}/pipelines",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "builds": BuildkiteEndpointConfig(
        name="builds",
        path="/v2/organizations/{organization}/builds",
        partition_key="created_at",
        # The builds list returns newest-first by created_at and accepts a `created_from` filter
        # (ISO 8601). We sync incrementally by passing created_from=<watermark> and paginating the
        # bounded window newest-first. `created_at` is immutable; a build's state/finished_at mutate
        # after it first appears, so a build that finishes after newer builds have landed won't be
        # re-fetched once it drops below the watermark. Full refresh re-pulls everything.
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort_mode="desc",
        incremental_param_map={"created_at": "created_from"},
    ),
    "agents": BuildkiteEndpointConfig(
        name="agents",
        path="/v2/organizations/{organization}/agents",
        partition_key="created_at",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(BUILDKITE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUILDKITE_ENDPOINTS.items()
}
