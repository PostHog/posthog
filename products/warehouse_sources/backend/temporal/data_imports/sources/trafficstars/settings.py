from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

TRAFFICSTARS_BASE_URL = "https://api.trafficstars.com"
TRAFFICSTARS_TOKEN_URL = "https://api.trafficstars.com/v1/auth/token"

CREATIVES_PAGE_SIZE = 100

# How far back the first sync of the daily statistics reads.
HISTORY_DAYS = 180

# TrafficStars documents no attribution window. Re-reading the last week picks up late conversions.
LOOKBACK_SECONDS = 7 * 24 * 60 * 60


@frozen
class TrafficStarsEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    incremental_fields: tuple[IncrementalField, ...] = ()
    partition_key: str | None = None


TRAFFICSTARS_ENDPOINTS: dict[str, TrafficStarsEndpointConfig] = {
    "campaigns": TrafficStarsEndpointConfig(
        name="campaigns", path="/v1.1/campaigns", data_selector="response", primary_keys=("id",)
    ),
    "creatives": TrafficStarsEndpointConfig(
        name="creatives", path="/v2/banners", data_selector="response", primary_keys=("id",)
    ),
    "campaign_statistics_daily": TrafficStarsEndpointConfig(
        name="campaign_statistics_daily",
        path="/v2/campaigns/statistics",
        data_selector="data",
        primary_keys=("date", "id"),
        incremental_fields=(
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ),
        partition_key="date",
    ),
}

ENDPOINTS = tuple(TRAFFICSTARS_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in TRAFFICSTARS_ENDPOINTS.items()
}

LOOKBACK: dict[str, int] = {"campaign_statistics_daily": LOOKBACK_SECONDS}

# Daily statistics re-read a trailing week each run. Appending would write those rows again.
MERGE_ONLY = ("campaign_statistics_daily",)
