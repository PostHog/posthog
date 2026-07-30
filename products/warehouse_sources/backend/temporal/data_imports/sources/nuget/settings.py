from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The well-known entry point of the public NuGet V3 API. Every other base URL (search,
# registrations, catalog) is discovered from this document at run time, per the API contract.
SERVICE_INDEX_URL = "https://api.nuget.org/v3/index.json"


@dataclass
class NugetEndpointConfig:
    name: str
    # True only for the catalog: its index exposes per-page commitTimeStamps, so a cursor can skip
    # already-synced pages server-side. Search and registrations are keyed by package id, not time.
    supports_incremental: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by. Only the catalog qualifies: its leaves are append-only and
    # immutable. `published` on package versions is NOT stable (unlisting rewrites it to 1900).
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    description: str | None = None


NUGET_ENDPOINTS: dict[str, NugetEndpointConfig] = {
    "packages": NugetEndpointConfig(
        name="packages",
        supports_incremental=False,
        description=(
            "One row per tracked package from NuGet search, including the total download count and "
            "verification status. Download totals are re-polled on every sync. Unlisted packages are "
            "hidden from NuGet search and skipped"
        ),
    ),
    "package_versions": NugetEndpointConfig(
        name="package_versions",
        supports_incremental=False,
        primary_keys=["id", "version"],
        description=(
            "One row per version of each tracked package from the NuGet registration index, with "
            "per-version download counts merged in from search"
        ),
    ),
    "catalog_events": NugetEndpointConfig(
        name="catalog_events",
        supports_incremental=True,
        partition_key="commit_timestamp",
        primary_keys=["catalog_leaf_url"],
        should_sync_default=False,
        description=(
            "Publish, edit, and delete events for the tracked packages from the append-only NuGet "
            "catalog. The first sync walks the full nuget.org catalog (tens of thousands of pages) and "
            "can take several hours; incremental syncs afterwards only read new catalog pages"
        ),
        incremental_fields=[
            {
                "label": "commit_timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "commit_timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(NUGET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NUGET_ENDPOINTS.items()
}
