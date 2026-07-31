from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

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


@dataclass
class RubyGemsEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column used for partitioning, or `None` for streams without one.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None


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
}

ENDPOINTS = tuple(RUBYGEMS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RUBYGEMS_ENDPOINTS.items()
}
