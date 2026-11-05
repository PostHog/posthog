from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# A version's `created_at` never changes once published, so it's a stable partition key for the
# versions stream. `gems` has no comparable stable timestamp (its `downloads`/`version` fields
# mutate as new releases land), so it's left unpartitioned.
_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=False)
class RubyGemsEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column used for partitioning, or `None` for streams without one.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None
    # Ecosystem-wide feeds ignore the configured gem list and make the same requests for every source.
    per_gem: bool = True
    supports_incremental: bool = False


RUBYGEMS_ENDPOINTS: dict[str, RubyGemsEndpointConfig] = {
    "gems": RubyGemsEndpointConfig(
        name="gems",
        # Gem names are globally unique on RubyGems.org.
        primary_keys=["name"],
        description="Current metadata and cumulative download count for each configured gem, from "
        "GET /api/v1/gems/{name}.json.",
    ),
    "versions": RubyGemsEndpointConfig(
        name="versions",
        # A version `number` is unique per gem, but can repeat across platforms (e.g. a native
        # extension gem publishing separate `ruby` and `java` builds of the same version), and
        # rows aggregate across every configured gem, so all three fields together form the key.
        primary_keys=["gem_name", "number", "platform"],
        incremental_fields=list(_CREATED_AT_INCREMENTAL_FIELDS),
        partition_key="created_at",
        description="Every published version of each configured gem, including per-version download "
        "counts, from GET /api/v1/versions/{name}.json.",
    ),
    "owners": RubyGemsEndpointConfig(
        name="owners",
        # Owner ids are global user ids, and one user can own many configured gems.
        primary_keys=["gem_name", "id"],
        description="Every owner and maintainer of each configured gem, from GET /api/v1/gems/{name}/owners.json.",
    ),
    "reverse_dependencies": RubyGemsEndpointConfig(
        name="reverse_dependencies",
        primary_keys=["gem_name", "dependent_name"],
        description="Every gem whose latest version depends on a configured gem, from "
        "GET /api/v1/gems/{name}/reverse_dependencies.json.",
    ),
    "latest_gems": RubyGemsEndpointConfig(
        name="latest_gems",
        primary_keys=["name"],
        should_sync_default=False,
        per_gem=False,
        description="The 50 gems most recently added to RubyGems.org, across the whole ecosystem, from "
        "GET /api/v1/activity/latest.json.",
    ),
    "just_updated_gems": RubyGemsEndpointConfig(
        name="just_updated_gems",
        # The feed has one row per pushed version, so a gem that ships several platforms in a row
        # appears once per platform.
        primary_keys=["name", "version", "platform"],
        should_sync_default=False,
        per_gem=False,
        description="The 50 most recently pushed gem versions, across the whole ecosystem, from "
        "GET /api/v1/activity/just_updated.json.",
    ),
    "timeframe_versions": RubyGemsEndpointConfig(
        name="timeframe_versions",
        primary_keys=["name", "number", "platform"],
        incremental_fields=list(_CREATED_AT_INCREMENTAL_FIELDS),
        partition_key="created_at",
        should_sync_default=False,
        per_gem=False,
        supports_incremental=True,
        description="Every gem version pushed to RubyGems.org, across the whole ecosystem, from "
        "GET /api/v1/timeframe_versions.json. A first sync reads the last 7 days.",
    ),
}

ENDPOINTS = tuple(RUBYGEMS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RUBYGEMS_ENDPOINTS.items()
}
