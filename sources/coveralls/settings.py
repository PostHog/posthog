from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# A build's creation time never changes, so it's a stable incremental cursor and partition key.
_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class CoverallsEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column used for partitioning, or `None` for streams without one.
    partition_key: Optional[str] = None
    # Requires the optional personal API token (the public builds feed does not).
    requires_api_token: bool = False
    should_sync_default: bool = True
    description: Optional[str] = None
    # Safety overlap subtracted from the incremental watermark before the desc walk stops, re-pulling
    # a window of builds that merge dedupes on the primary key. Covers builds that land in an
    # already-fetched repository while a multi-repository sync is still running (the persisted
    # watermark is the max across every repository in the run).
    incremental_lookback: Optional[timedelta] = None


COVERALLS_ENDPOINTS: dict[str, CoverallsEndpointConfig] = {
    "builds": CoverallsEndpointConfig(
        name="builds",
        # Build ids look globally unique (one sequence across coveralls.io), but that isn't
        # documented — the repository name makes the key robust either way.
        primary_keys=["repo_name", "id"],
        incremental_fields=list(_CREATED_AT_INCREMENTAL_FIELDS),
        partition_key="created_at",
        incremental_lookback=timedelta(hours=24),
        description="Coverage builds: one row per CI build across every configured repository, "
        "with covered/missed/relevant line and branch counts, coverage change, and commit metadata.",
    ),
    "repositories": CoverallsEndpointConfig(
        name="repositories",
        primary_keys=["service", "name"],
        requires_api_token=True,
        # Requires the optional personal API token, which source creation doesn't validate — the
        # schema picker leaves it off so an untokened source doesn't fail on its first sync.
        should_sync_default=False,
        description="Repository configuration: one row per configured repository from the "
        "`/api/v1/repos` endpoint. Requires a personal API token.",
    ),
}

ENDPOINTS = tuple(COVERALLS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COVERALLS_ENDPOINTS.items()
}
