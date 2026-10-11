from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Packagist download stats lag ~1-2 days behind real time and the trailing day is partial, so
# incremental syncs re-read a trailing window instead of freezing days at their first value.
_DOWNLOADS_LOOKBACK_SECONDS = 3 * 24 * 60 * 60

_DOWNLOADS_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class PackagistEndpointConfig:
    name: str
    primary_keys: list[str]
    # `True` only when the API endpoint takes a server-side filter (the stats endpoints'
    # `from`/`to` date window). Metadata endpoints return the full document every time.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime/date column used for partitioning, or `None` for streams without one.
    partition_key: Optional[str] = None
    default_incremental_lookback_seconds: Optional[int] = None
    should_sync_default: bool = True
    description: Optional[str] = None


PACKAGIST_ENDPOINTS: dict[str, PackagistEndpointConfig] = {
    "packages": PackagistEndpointConfig(
        name="packages",
        # Packagist package names (`vendor/package`) are globally unique.
        primary_keys=["name"],
        description="Package metadata: one row per configured package with description, type, "
        "repository, download totals, GitHub stats, and maintainers.",
    ),
    "versions": PackagistEndpointConfig(
        name="versions",
        # Versions aggregate across packages into one table, so the package name is part of the key.
        primary_keys=["package", "version"],
        # No partition key: tagged versions have a stable `time`, but branch versions
        # (`dev-main`, `2.x-dev`) restamp `time` on every commit, which would rewrite partitions.
        description="Package versions: one row per released version (and dev branch) of each "
        "configured package, with dependencies, dist/source links, and license.",
    ),
    "downloads": PackagistEndpointConfig(
        name="downloads",
        primary_keys=["package", "date"],
        # The stats endpoint takes a server-side `from`/`to` date window (curl-verified), so this
        # stream is genuinely incremental on `date`.
        supports_incremental=True,
        incremental_fields=list(_DOWNLOADS_INCREMENTAL_FIELDS),
        # A day's download count never moves to another day, so `date` is a stable partition key.
        partition_key="date",
        default_incremental_lookback_seconds=_DOWNLOADS_LOOKBACK_SECONDS,
        description="Daily download statistics: one row per configured package per day.",
    ),
    "security_advisories": PackagistEndpointConfig(
        name="security_advisories",
        # Advisory ids repeat across packages only via distinct packageName rows.
        primary_keys=["packageName", "advisoryId"],
        description="Security advisories affecting the configured packages, as reported by the "
        "Packagist security advisories API.",
    ),
}

ENDPOINTS = tuple(PACKAGIST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PACKAGIST_ENDPOINTS.items()
}
