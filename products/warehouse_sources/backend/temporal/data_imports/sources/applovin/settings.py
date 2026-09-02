from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

APPLOVIN_API_BASE_URL = "https://r.applovin.com"

# Every reporting endpoint rejects dates outside a rolling 45-day window, so 45 days is the
# deepest history the API can serve — older data is not retrievable through the API at all.
MAX_REQUEST_WINDOW_DAYS = 45
# Report rows for recent days restate as attribution and cohort metrics settle, so incremental
# runs re-pull a trailing window and merge on the dimension tuple.
REPORT_LOOKBACK_DAYS = 7
# Request in bounded date chunks so a single response doesn't carry the whole window. Kept equal
# to the lookback so one window is always fully re-read after a mid-window failure.
REPORT_WINDOW_DAYS = 7
# `limit`/`offset` page size. AppLovin documents no maximum; 1000 is the value used in its own
# pagination example.
REPORT_PAGE_SIZE = 1000

# The cohort endpoints expose one metric per (metric, days-since-install) pair. AppLovin accepts
# 0, 1, 2, 3, 4, 5, 6, 7, 10, 14, 18, 21, 24, 27, 30 and 45; we request a useful subset because
# every extra horizon multiplies the column count.
COHORT_DAY_OFFSETS = (0, 1, 3, 7, 14, 30)

COHORT_DIMENSIONS = ["day", "application", "package_name", "platform", "country"]
COHORT_PRIMARY_KEYS = ["day", "package_name", "platform", "country"]


def cohort_metrics(prefixes: tuple[str, ...]) -> list[str]:
    """Expand per-horizon cohort metric prefixes into concrete column names."""
    return [f"{prefix}_{offset}" for prefix in prefixes for offset in COHORT_DAY_OFFSETS]


@dataclass
class AppLovinEndpointConfig:
    name: str
    # Path under `https://r.applovin.com`.
    path: str
    # Grouping columns. AppLovin has no fixed schema: the requested `columns` decide both the
    # grain of the aggregate and the shape of each row.
    dimensions: list[str]
    metrics: list[str]
    # Subset of `dimensions` that identifies a row. Excludes columns that are functionally
    # determined by another key column (an app's display name, a campaign's name) so a rename
    # upstream doesn't fork a row into two.
    primary_keys: list[str]
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def columns(self) -> list[str]:
        return [*self.dimensions, *self.metrics]


APPLOVIN_ENDPOINTS: dict[str, AppLovinEndpointConfig] = {
    # MAX mediation revenue at network grain. `requests` is unavailable whenever `network` or
    # `network_placement` is requested, which is why the ad-unit table below exists separately.
    "max_ad_revenue": AppLovinEndpointConfig(
        name="max_ad_revenue",
        path="/maxReport",
        dimensions=[
            "day",
            "application",
            "package_name",
            "store_id",
            "platform",
            "country",
            "device_type",
            "ad_format",
            "max_ad_unit",
            "max_ad_unit_id",
            "network",
        ],
        metrics=["impressions", "attempts", "responses", "fill_rate", "ecpm", "estimated_revenue"],
        primary_keys=[
            "day",
            "package_name",
            "platform",
            "country",
            "device_type",
            "ad_format",
            "max_ad_unit_id",
            "network",
        ],
    ),
    # Same report without the network dimension, which is the only way to get `requests`.
    "max_ad_unit_revenue": AppLovinEndpointConfig(
        name="max_ad_unit_revenue",
        path="/maxReport",
        dimensions=[
            "day",
            "application",
            "package_name",
            "store_id",
            "platform",
            "country",
            "device_type",
            "ad_format",
            "max_ad_unit",
            "max_ad_unit_id",
        ],
        metrics=["impressions", "requests", "ecpm", "estimated_revenue"],
        primary_keys=[
            "day",
            "package_name",
            "platform",
            "country",
            "device_type",
            "ad_format",
            "max_ad_unit_id",
        ],
    ),
    "publisher_report": AppLovinEndpointConfig(
        name="publisher_report",
        path="/report",
        dimensions=[
            "day",
            "application",
            "package_name",
            "store_id",
            "platform",
            "country",
            "device_type",
            "ad_type",
            "placement_type",
            "size",
            "bidding_integration",
        ],
        metrics=["impressions", "clicks", "ctr", "ecpm", "revenue"],
        primary_keys=[
            "day",
            "package_name",
            "platform",
            "country",
            "device_type",
            "ad_type",
            "placement_type",
            "size",
            "bidding_integration",
        ],
        extra_params={"report_type": "publisher"},
    ),
    "advertiser_report": AppLovinEndpointConfig(
        name="advertiser_report",
        path="/report",
        dimensions=[
            "day",
            "campaign",
            "campaign_id_external",
            "campaign_type",
            "campaign_ad_type",
            "campaign_package_name",
            "application",
            "app_id_external",
            "platform",
            "country",
            "device_type",
            "ad_type",
            "size",
        ],
        metrics=[
            "cost",
            "impressions",
            "clicks",
            "ctr",
            "conversions",
            "conversion_rate",
            "average_cpa",
            "average_cpc",
            "sales",
        ],
        primary_keys=[
            "day",
            "campaign_id_external",
            "app_id_external",
            "platform",
            "country",
            "device_type",
            "ad_type",
            "size",
        ],
        extra_params={"report_type": "advertiser"},
    ),
    "max_cohort_ad_revenue": AppLovinEndpointConfig(
        name="max_cohort_ad_revenue",
        path="/maxCohort",
        dimensions=list(COHORT_DIMENSIONS),
        metrics=[
            "installs",
            *cohort_metrics(("pub_revenue", "rpi", "ads_pub_revenue", "iap_pub_revenue")),
        ],
        primary_keys=list(COHORT_PRIMARY_KEYS),
    ),
    "max_cohort_impressions": AppLovinEndpointConfig(
        name="max_cohort_impressions",
        path="/maxCohort/imp",
        dimensions=list(COHORT_DIMENSIONS),
        metrics=["installs", *cohort_metrics(("imp", "imp_per_user", "user_count"))],
        primary_keys=list(COHORT_PRIMARY_KEYS),
    ),
    "max_cohort_sessions": AppLovinEndpointConfig(
        name="max_cohort_sessions",
        path="/maxCohort/session",
        dimensions=list(COHORT_DIMENSIONS),
        metrics=[
            "installs",
            *cohort_metrics(("user_count", "retention", "session_count", "daily_usage", "session_length")),
        ],
        primary_keys=list(COHORT_PRIMARY_KEYS),
    ),
}

ENDPOINTS = tuple(APPLOVIN_ENDPOINTS.keys())

# Every endpoint is a date-partitioned report filtered server-side by `start`/`end` on `day`.
DAY_INCREMENTAL_FIELD: IncrementalField = {
    "label": "day",
    "type": IncrementalFieldType.DateTime,
    "field": "day",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [DAY_INCREMENTAL_FIELD] for name in ENDPOINTS}
