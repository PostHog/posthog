from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# A download row's day never changes once the day is over, so it's a stable incremental/partition
# field. npm's downloads-range API is a genuine server-side date-window filter (we only request the
# days we don't have yet), unlike the registry document below.
_DOWNLOADS_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "day",
        "type": IncrementalFieldType.Date,
        "field": "day",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class NpmRegistryEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition/checkpoint by, or `None` for streams without one.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None


NPM_REGISTRY_ENDPOINTS: dict[str, NpmRegistryEndpointConfig] = {
    "Downloads": NpmRegistryEndpointConfig(
        name="Downloads",
        # A day's download count is only ever reported once per configured package.
        primary_keys=["package", "day"],
        incremental_fields=list(_DOWNLOADS_INCREMENTAL_FIELDS),
        partition_key="day",
        description="Daily download counts per configured package, from the npm downloads-counts API.",
    ),
    "Versions": NpmRegistryEndpointConfig(
        name="Versions",
        # A version string is only unique within its own package.
        primary_keys=["package", "version"],
        # The registry document has no server-side "changed since" filter — every sync re-fetches
        # the whole document per package, so this stays full refresh (see npm_registry.py).
        partition_key="published_at",
        description="Published version metadata (publish time, dist-tags, tarball, license) per "
        "configured package, from the npm registry API.",
    ),
}

ENDPOINTS = tuple(NPM_REGISTRY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NPM_REGISTRY_ENDPOINTS.items()
}

# npm's download-counts API has no data before this date.
EARLIEST_DOWNLOAD_DATE = "2015-01-10"

# The range endpoint doesn't error past ~18 months — it silently returns only the *tail* of the
# requested window instead (verified: requesting 2015-01-10:2020-01-10 returns only the last ~550
# days, ending 2020-01-10, not the first). Always request windows no larger than this or older
# history is dropped without any error to catch it.
MAX_DOWNLOADS_WINDOW_DAYS = 540

# Each configured package costs at least one request per enabled stream every sync (more for a long
# Downloads backfill), and the registry document for a popular package can run several MB. Cap the
# config so a large list can't tie up the worker indefinitely.
MAX_PACKAGES = 100

# Rows for a single package's Versions stream are yielded in bounded chunks so a package with a huge
# version history (some popular packages have thousands of versions) never forces one oversized
# in-memory batch. The pipeline batches on top of this; this value only caps the per-yield list size.
MAX_ROWS_PER_BATCH = 5000

# Hard cap on the raw bytes we'll buffer for a single npm response before parsing JSON. The registry
# document is user-selected (anyone can publish a package and point a source at it), so without a cap
# a package crafted with enough versions/metadata could make one response exhaust the worker's memory.
# Set well above the largest real full-registry documents (tens of MB) so legitimate packages sync,
# while still bounding the pathological case.
MAX_RESPONSE_BYTES = 250 * 1024 * 1024
