from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.criteo.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
API_VERSION = "2026-07"
REPORT_ROW_LIMIT = 100_000
REPORT_DIMENSIONS = ["Day", "AdvertiserId", "CampaignId"]
REPORT_METRICS = [
    "Displays",
    "Clicks",
    "AdvertiserCost",
    "SalesClientAttribution",
    "RevenueGeneratedClientAttribution",
]


@frozen
class CriteoEndpoint:
    name: str
    path: str
    description: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "id"
    partition_mode: PartitionMode = "md5"
    partition_format: PartitionFormat | None = None
    partition_count: int = 16
    method: Literal["GET", "POST"] = "GET"
    page_size: int = 0
    total_path: str | None = None
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


ENDPOINTS: dict[str, CriteoEndpoint] = {
    "Advertisers": CriteoEndpoint(
        name="Advertisers",
        path="advertisers/me",
        description="Advertisers that granted access to the Criteo application.",
    ),
    "Campaigns": CriteoEndpoint(
        name="Campaigns",
        path="marketing-solutions/campaigns/search",
        method="POST",
        description="Campaign settings and advertising objectives.",
    ),
    "AdSets": CriteoEndpoint(
        name="AdSets",
        path="marketing-solutions/ad-sets/search",
        method="POST",
        description="Ad set settings, budgets, bids, schedules, and targeting.",
    ),
    "Ads": CriteoEndpoint(
        name="Ads",
        path="marketing-solutions/advertisers/{advertiser-id}/ads",
        page_size=50,
        primary_keys=("advertiserId", "id"),
        fanout=DependentEndpointConfig(
            parent_name="Advertisers",
            resolve_param="advertiser-id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "advertiserId"},
        ),
        description="Ads that link creatives to ad sets, with their delivery status and schedule.",
    ),
    "Audiences": CriteoEndpoint(
        name="Audiences",
        path="marketing-solutions/audiences/search",
        method="POST",
        page_size=100,
        total_path="meta.totalItems",
        description="Audience definitions and their linked segments.",
    ),
    "CampaignStats": CriteoEndpoint(
        name="CampaignStats",
        path="statistics/report",
        method="POST",
        primary_keys=("AdvertiserId", "CampaignId", "Day"),
        partition_key="Day",
        partition_mode="datetime",
        partition_format="month",
        partition_count=1,
        description="Daily campaign impressions, clicks, cost, attributed sales, and revenue in the selected currency.",
    ),
}

# Date bounds follow Criteo's specification. Live account verification is still required.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "CampaignStats": [incremental_field("Day", IncrementalFieldType.Date)],
}
DEFAULT_LOOKBACK_SECONDS = {"CampaignStats": 30 * 24 * 60 * 60}
