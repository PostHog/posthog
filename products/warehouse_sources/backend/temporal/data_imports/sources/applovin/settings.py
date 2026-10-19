from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

APPLOVIN_API_BASE_URL = "https://r.applovin.com"
# The Campaign Management API authenticates with its own key, separate from the Report Key.
APPLOVIN_MANAGEMENT_API_BASE_URL = "https://api.ads.axon.ai/manage/v1"

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

USER_AD_REVENUE_ENDPOINT = "user_ad_revenue"
USER_AD_REVENUE_PATH = "/max/userAdRevenueReport"
# The report is per (app, day), so the apps with MAX revenue on a day are listed first.
USER_AD_REVENUE_APPS = AppLovinEndpointConfig(
    name="user_ad_revenue_apps",
    path="/maxReport",
    dimensions=["day", "package_name", "platform"],
    metrics=["impressions"],
    primary_keys=["day", "package_name", "platform"],
)
# A day's report is final once it is published, eight hours after the UTC day ends. Re-reading
# the last synced day picks up a day whose report was not yet published on the previous run.
USER_AD_REVENUE_LOOKBACK_DAYS = 1
USER_AD_REVENUE_BATCH_SIZE = 5000
# The aggregated report has one row per user and ad placement, and every string column of the CSV
# is part of that grain. A column the CSV leaves out is filled with "" so the key is never null.
USER_AD_REVENUE_PRIMARY_KEYS = [
    "day",
    "package_name",
    "platform",
    "ad_unit_id",
    "placement",
    "idfa",
    "idfv",
    "user_id",
    "custom_data",
]


@dataclass(frozen=True)
class AppLovinManagementEndpointConfig:
    name: str
    # Path under `APPLOVIN_MANAGEMENT_API_BASE_URL`.
    path: str
    primary_keys: list[str]
    partition_key: Optional[str] = None


# `size` maximum on every Campaign Management list endpoint.
MANAGEMENT_PAGE_SIZE = 100
# `/operation_logs/campaign` rejects dates older than the latest 30 UTC days, today included.
OPERATION_LOG_WINDOW_DAYS = 30

MANAGEMENT_ENDPOINTS: dict[str, AppLovinManagementEndpointConfig] = {
    "campaigns": AppLovinManagementEndpointConfig(
        name="campaigns", path="/campaign/list", primary_keys=["id"], partition_key="created_at"
    ),
    "creative_sets": AppLovinManagementEndpointConfig(
        name="creative_sets", path="/creative_set/list", primary_keys=["id"]
    ),
    "campaign_operation_logs": AppLovinManagementEndpointConfig(
        name="campaign_operation_logs",
        path="/operation_logs/campaign",
        primary_keys=["operation_id"],
        partition_key="operation_time",
    ),
}

ENDPOINTS = (*APPLOVIN_ENDPOINTS.keys(), USER_AD_REVENUE_ENDPOINT, *MANAGEMENT_ENDPOINTS.keys())

PRIMARY_KEYS: dict[str, list[str]] = {
    **{name: config.primary_keys for name, config in APPLOVIN_ENDPOINTS.items()},
    USER_AD_REVENUE_ENDPOINT: USER_AD_REVENUE_PRIMARY_KEYS,
    **{name: config.primary_keys for name, config in MANAGEMENT_ENDPOINTS.items()},
}

# The report endpoints are filtered server-side by `start`/`end` (or `date`) on `day`.
DAY_INCREMENTAL_FIELD: IncrementalField = {
    "label": "day",
    "type": IncrementalFieldType.DateTime,
    "field": "day",
    "field_type": IncrementalFieldType.DateTime,
}

# Operation logs are filtered server-side by `start_date`/`end_date`. Campaigns and creative sets
# have no server-side filter, so they sync as a full refresh.
OPERATION_TIME_INCREMENTAL_FIELD: IncrementalField = {
    "label": "operation_time",
    "type": IncrementalFieldType.DateTime,
    "field": "operation_time",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{name: [DAY_INCREMENTAL_FIELD] for name in (*APPLOVIN_ENDPOINTS.keys(), USER_AD_REVENUE_ENDPOINT)},
    "campaign_operation_logs": [OPERATION_TIME_INCREMENTAL_FIELD],
}

# Report rows restate as metrics settle, and operation log syncs re-read the watermark day, so
# append would duplicate rows in both.
MERGE_ONLY_ENDPOINTS = (*APPLOVIN_ENDPOINTS.keys(), USER_AD_REVENUE_ENDPOINT, "campaign_operation_logs")
