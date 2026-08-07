from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

TRANSISTOR_BASE_URL = "https://api.transistor.fm/v1"

# The docs give `pagination[per]` a default of 10 without stating a cap. 100 is what other
# published Transistor integrations use; pagination terminates on the response's `meta`
# block rather than on the page length, so a server-side clamp to a smaller page is handled.
PAGE_SIZE = 100

# Transistor allows 10 requests per 10 seconds and blocks for 10 seconds once exceeded, so
# requests are paced just over one per second instead of relying on 429 backoff alone.
MIN_REQUEST_INTERVAL_SECONDS = 1.1

# Fan-out endpoints issue at least one request per show on every sync, so the parent list is
# capped to bound a sync's outbound request count.
MAX_SHOWS = 500

# The analytics endpoints take an arbitrary start/end date range and answer in one response
# (no pagination), but the docs don't state a maximum range. Requests are windowed so a long
# backfill is split into predictable chunks that also act as resume checkpoints.
ANALYTICS_WINDOW_DAYS = 365

# How far back a first (non-incremental) analytics sync reaches when a show's creation date
# can't be read from the show row.
ANALYTICS_MAX_BACKFILL_DAYS = 5 * 365

# Podcast downloads for a given day keep accruing for weeks as listeners catch up, so
# incremental analytics syncs re-read a trailing window instead of freezing each day at its
# first-imported value.
ANALYTICS_LOOKBACK_SECONDS = 14 * 24 * 60 * 60

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [incremental_field("date", IncrementalFieldType.Date)]


@dataclass
class TransistorEndpointConfig:
    name: str
    primary_keys: list[str]
    # `True` only for the analytics endpoints, which take a server-side `start_date`/`end_date`
    # window. The entity list endpoints have no updated-since filter, so they are full refresh.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable date/datetime column used for partitioning; never a mutable timestamp.
    partition_key: Optional[str] = None
    default_incremental_lookback_seconds: Optional[int] = None
    description: Optional[str] = None


TRANSISTOR_ENDPOINTS: dict[str, TransistorEndpointConfig] = {
    "shows": TransistorEndpointConfig(
        name="shows",
        primary_keys=["id"],
        description="Podcasts on the account, one row per show, with title, description, "
        "category, feed URL, and privacy settings.",
    ),
    "episodes": TransistorEndpointConfig(
        name="episodes",
        # Episode ids are account-wide identifiers, so the show id is carried as a column but
        # is not needed to make the key unique.
        primary_keys=["id"],
        partition_key="created_at",
        description="Episodes across every show on the account, including drafts and scheduled "
        "episodes, with audio, artwork, and publishing metadata.",
    ),
    "subscribers": TransistorEndpointConfig(
        name="subscribers",
        # Fetched per show, so the show id is part of the key even though subscriber ids look
        # account-wide — the docs don't promise global uniqueness.
        primary_keys=["show_id", "id"],
        partition_key="created_at",
        description="Private podcast subscribers, one row per subscriber per show. Only shows "
        "marked private have subscribers.",
    ),
    "webhooks": TransistorEndpointConfig(
        name="webhooks",
        primary_keys=["show_id", "id"],
        description="Webhook subscriptions registered on each show, with the subscribed event name and delivery URL.",
    ),
    "show_analytics": TransistorEndpointConfig(
        name="show_analytics",
        primary_keys=["show_id", "date"],
        supports_incremental=True,
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
        # A day's download count never moves to another day, so `date` is a stable partition key.
        partition_key="date",
        default_incremental_lookback_seconds=ANALYTICS_LOOKBACK_SECONDS,
        description="Daily download counts per show, one row per show per day.",
    ),
    "episode_analytics": TransistorEndpointConfig(
        name="episode_analytics",
        primary_keys=["show_id", "episode_id", "date"],
        supports_incremental=True,
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
        partition_key="date",
        default_incremental_lookback_seconds=ANALYTICS_LOOKBACK_SECONDS,
        description="Daily download counts per episode, one row per episode per day.",
    ),
}

ENDPOINTS = tuple(TRANSISTOR_ENDPOINTS.keys())

# Endpoints fetched once per show. `shows` is the parent list itself.
FANOUT_ENDPOINTS = tuple(name for name in ENDPOINTS if name != "shows")

# Endpoints that walk pages of a JSON:API list rather than a date-windowed analytics document.
PAGINATED_ENDPOINTS = ("shows", "episodes", "subscribers", "webhooks")

ANALYTICS_ENDPOINTS = ("show_analytics", "episode_analytics")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRANSISTOR_ENDPOINTS.items()
}
