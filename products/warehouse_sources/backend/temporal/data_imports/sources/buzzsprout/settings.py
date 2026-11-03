from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
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
    # Endpoints that take one required `date` per request are walked day by day.
    fan_out_over_days: bool = False
    default_incremental_lookback_seconds: Optional[int] = None
    description: Optional[str] = None


# Buzzsprout's list resources return the full unpaginated array on every request with no server-side
# timestamp filter, so they are full refresh only. `downloads` is the exception: it is queried one day
# at a time, so the day itself is the server-side filter.
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
    "downloads": BuzzsproutEndpointConfig(
        name="downloads",
        path="downloads.json",
        # The endpoint returns one row per episode with downloads that day, and the row does not name
        # the day, so the day is stamped on and forms part of the key.
        primary_keys=["date", "episode_id"],
        partition_key="date",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        fan_out_over_days=True,
        # The last synced day can still be in progress in the podcast's time zone, so re-read it.
        default_incremental_lookback_seconds=2 * 24 * 60 * 60,
        description="Daily download totals per episode, by podcast-local date. A full refresh reads every "
        "day since the first published episode, one request per day.",
    ),
    "contributors": BuzzsproutEndpointConfig(
        name="contributors",
        path="contributors.json",
        description="On-show credits (hosts, co-hosts, producers, editors and guests) for the configured "
        "podcast. Full refresh.",
    ),
    "fan_mail": BuzzsproutEndpointConfig(
        name="fan_mail",
        path="fan_mail.json",
        partition_key="created_at",
        description="Unblocked listener messages sent to the configured podcast. Full refresh.",
    ),
    "listings": BuzzsproutEndpointConfig(
        name="listings",
        path="listings.json",
        # Directories the podcast was never submitted to have a null `id`, so key on the directory.
        primary_keys=["directory"],
        description="Podcast directory listings (Apple Podcasts, Spotify and others) and their status. Full refresh.",
    ),
}

ENDPOINTS = tuple(BUZZSPROUT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUZZSPROUT_ENDPOINTS.items()
}
