from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CRITEO_BASE_URL = "https://api.criteo.com"
CRITEO_TOKEN_URL = f"{CRITEO_BASE_URL}/oauth2/token"

# Criteo date-versions the Marketing Solutions API and sunsets old versions, so the version segment
# is part of every path. Pin the one the request layer below actually calls.
CRITEO_API_VERSION = "2026-01"

# "portfolio" — the single advertisers/me listing.
# "search"    — a POST search endpoint that returns the whole collection in one response.
# "paged"     — a listing with `limit`/`offset` query pagination.
# "report"    — the synchronous statistics report, walked in date windows.
EndpointKind = Literal["portfolio", "search", "paged", "report"]

# `Day` is the report's date grain and the only server-side time filter Criteo exposes
# (startDate/endDate on the report body), so it's the one incremental cursor available.
_DAY_INCREMENTAL_FIELDS: list[IncrementalField] = [incremental_field("Day", IncrementalFieldType.Date)]

# Criteo keeps revising conversion and revenue metrics for weeks after the click, so each incremental
# run re-reads a trailing window instead of freezing a day at its first-imported value. Mirrors the
# 30-day rollback other warehouse vendors use for Criteo reporting.
STATS_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class CriteoEndpointConfig:
    name: str
    # Path under the version segment. `{advertiser_id}` is filled per advertiser when fanning out.
    path: str
    kind: EndpointKind
    primary_key: list[str]
    # OAuth scope Criteo requires for the endpoint, surfaced in the source caption. None where the
    # reference documents no scope beyond a valid token (the portfolio listing).
    scope: Optional[str] = None
    # Fanned out over every advertiser in the portfolio; rows carry `_advertiser_id`.
    per_advertiser: bool = False
    # POST body sent alongside the pagination params, for the search endpoints.
    body: Optional[dict[str, object]] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time (or report-day) field used for datetime partitioning.
    partition_key: Optional[str] = None
    default_incremental_lookback_seconds: Optional[int] = None


CRITEO_ENDPOINTS: dict[str, CriteoEndpointConfig] = {
    "advertisers": CriteoEndpointConfig(
        name="advertisers",
        path="/advertisers/me",
        kind="portfolio",
        primary_key=["id"],
    ),
    "campaigns": CriteoEndpointConfig(
        name="campaigns",
        path="/marketing-solutions/campaigns/search",
        kind="search",
        primary_key=["id"],
        scope="MarketingSolutions_Campaign_Read",
        # Empty filters means "everything in the portfolio".
        body={"filters": {}},
    ),
    "ad_sets": CriteoEndpointConfig(
        name="ad_sets",
        path="/marketing-solutions/ad-sets/search",
        kind="search",
        primary_key=["id"],
        scope="MarketingSolutions_Campaign_Read",
        body={"filters": {}},
    ),
    "ads": CriteoEndpointConfig(
        name="ads",
        path="/marketing-solutions/advertisers/{advertiser_id}/ads",
        kind="paged",
        # The reference doesn't state that ad ids are unique across advertisers, so the advertiser the
        # row was fanned out from is part of the key.
        primary_key=["_advertiser_id", "id"],
        scope="MarketingSolutions_Creative_Read",
        per_advertiser=True,
    ),
    "audiences": CriteoEndpointConfig(
        name="audiences",
        path="/marketing-solutions/audiences/search",
        kind="paged",
        primary_key=["id"],
        scope="MarketingSolutions_Audience_Read",
        body={"data": {"attributes": {}}},
        partition_key="createdAt",
    ),
    "campaign_stats": CriteoEndpointConfig(
        name="campaign_stats",
        path="/statistics/report",
        kind="report",
        primary_key=["AdvertiserId", "CampaignId", "Day"],
        incremental_fields=list(_DAY_INCREMENTAL_FIELDS),
        partition_key="Day",
        default_incremental_lookback_seconds=STATS_LOOKBACK_SECONDS,
    ),
}

# Report grain: one row per advertiser, campaign and day. Adding the human-readable name dimensions
# alongside the ids keeps the table joinable and readable without a second lookup.
REPORT_DIMENSIONS: tuple[str, ...] = ("Day", "AdvertiserId", "Advertiser", "CampaignId", "Campaign")

# Delivery, cost and 30-day post-click conversion metrics — the set that covers spend/ROAS reporting
# without pulling all ~180 metrics Criteo offers.
REPORT_METRICS: tuple[str, ...] = (
    "Displays",
    "Clicks",
    "AdvertiserCost",
    "Visits",
    "SalesAllPc30d",
    "RevenueGeneratedAllPc30d",
    "ConversionRateAllPc30d",
    "RoasAllPc30d",
    "Cpc",
    "ClickThroughRate",
)

# Report currency and timezone are required/defaulted by the endpoint; used when the form leaves them blank.
DEFAULT_REPORT_CURRENCY = "USD"
DEFAULT_REPORT_TIMEZONE = "UTC"

ENDPOINTS = tuple(CRITEO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CRITEO_ENDPOINTS.items() if config.incremental_fields
}

# The report table merges restated days rather than appending them, so append-only is not offered.
MERGE_ONLY_ENDPOINTS: tuple[str, ...] = ("campaign_stats",)
