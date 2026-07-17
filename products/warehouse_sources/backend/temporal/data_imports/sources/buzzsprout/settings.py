from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class BuzzsproutEndpointConfig:
    name: str
    # Path suffix after the (optional) podcast_id segment, e.g. "episodes.json". Buzzsprout requires
    # the ".json" extension — a missing/other extension returns 415 Unsupported Media Type.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time datetime column used for partitioning. Never an `updated_at`-style field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    # Account-scoped endpoints are called without the podcast_id path segment (e.g. /api/podcasts.json).
    account_scoped: bool = False
    description: Optional[str] = None


# Buzzsprout's v1 API exposes two list resources, both returning the full unpaginated array on every
# request with no server-side timestamp filter — so both are full refresh only.
BUZZSPROUT_ENDPOINTS: dict[str, BuzzsproutEndpointConfig] = {
    "episodes": BuzzsproutEndpointConfig(
        name="episodes",
        path="episodes.json",
        # `published_at` is the episode's publication time; it doesn't move once set, so it's a stable
        # partition key (unlike play counts or edit timestamps).
        partition_key="published_at",
        description="Every episode for the configured podcast. Full refresh — Buzzsprout returns the "
        "complete list on each request and exposes no server-side incremental filter.",
    ),
    "podcasts": BuzzsproutEndpointConfig(
        name="podcasts",
        path="podcasts.json",
        # Account-scoped: returns every podcast the API token can access, so it omits the podcast_id
        # path segment. No datetime field to partition on.
        account_scoped=True,
        description="Podcasts the API token can access, with their metadata. Full refresh.",
    ),
}

ENDPOINTS = tuple(BUZZSPROUT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUZZSPROUT_ENDPOINTS.items()
}
