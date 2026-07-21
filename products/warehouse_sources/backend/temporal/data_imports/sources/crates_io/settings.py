from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# A version's publish time never changes once released, so it's a stable partition key for the
# versions stream. Exposed as the raw ISO 8601 string crates.io already returns (`created_at`).
_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# A download row's date never changes; counts for a given day are final once the day is over.
_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class CratesIOEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column used for partitioning, or `None` for streams without one.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None


CRATES_IO_ENDPOINTS: dict[str, CratesIOEndpointConfig] = {
    "crates": CratesIOEndpointConfig(
        name="crates",
        # A crate's id is its globally unique name.
        primary_keys=["id"],
        description="Crate metadata: one row per configured crate, from the `crate` block of the "
        "crates.io API crate detail endpoint.",
    ),
    "versions": CratesIOEndpointConfig(
        name="versions",
        # crates.io version ids are numeric and unique across the whole registry (the downloads
        # endpoint references versions by this id alone).
        primary_keys=["id"],
        incremental_fields=list(_CREATED_AT_INCREMENTAL_FIELDS),
        partition_key="created_at",
        description="Published versions: one row per version across every configured crate.",
    ),
    "downloads": CratesIOEndpointConfig(
        name="downloads",
        # One row per crate + day + version id. Downloads crates.io only reports in aggregate
        # (versions outside the per-version breakdown) carry the sentinel version id 0.
        primary_keys=["crate", "date", "version"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
        partition_key="date",
        description="Daily download counts per version of each configured crate, over the trailing "
        "~90-day window the crates.io API exposes.",
    ),
    "owners": CratesIOEndpointConfig(
        name="owners",
        # Owner (user/team) ids are global on crates.io; rows aggregate across crates.
        primary_keys=["crate", "id"],
        description="Owners (users and teams) of each configured crate.",
    ),
}

ENDPOINTS = tuple(CRATES_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CRATES_IO_ENDPOINTS.items()
}
