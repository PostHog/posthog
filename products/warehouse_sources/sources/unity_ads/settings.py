from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

UNITY_STATS_URL = "https://services.api.unity.com/advertise/stats/v2/organizations/{organization_id}/reports/{report}"
UNITY_MANAGEMENT_URL = "https://services.api.unity.com/advertise/v1/organizations/{organization_id}"

# Unity keeps two years of statistics. The first sync reads one, to stay inside the rate limit of 30
# requests per 30 minutes.
HISTORY_DAYS = 365

# Post-install metrics such as d7 revenue keep changing for 28 days after the install.
LOOKBACK_SECONDS = 30 * 24 * 60 * 60

METRICS = (
    "starts",
    "views",
    "clicks",
    "installs",
    "spend",
    "cpi",
    "ctr",
    "cvr",
    "ecpm",
    "d7AdRevenue",
    "d7IapRevenue",
    "d7TotalRoas",
    "d7Retained",
)

_TIMESTAMP: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.Date,
    "field": "timestamp",
    "field_type": IncrementalFieldType.Date,
}


@frozen
class UnityAdsEndpointConfig:
    breakdowns: tuple[str, ...]
    primary_keys: tuple[str, ...]
    # Unity counts the stats quota per IP address. After a 429, a retry resumes at the saved window.
    window_days: int
    report: str = "acquisitions"
    metrics: tuple[str, ...] = METRICS


UNITY_ADS_ENDPOINTS: dict[str, UnityAdsEndpointConfig] = {
    "campaigns_daily": UnityAdsEndpointConfig(
        breakdowns=("campaign",),
        primary_keys=("timestamp", "campaignId"),
        window_days=92,
    ),
    "campaigns_daily_by_country": UnityAdsEndpointConfig(
        breakdowns=("campaign", "country"),
        primary_keys=("timestamp", "campaignId", "country"),
        window_days=31,
    ),
    "skan_daily": UnityAdsEndpointConfig(
        report="skan",
        metrics=("installs",),
        breakdowns=("campaign", "conversionValue"),
        primary_keys=("timestamp", "campaignId", "conversionValue"),
        window_days=31,
    ),
}

MANAGEMENT_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "apps": ("id",),
    "campaigns": ("campaignSetId", "id"),
    "cpi_bids": ("campaignSetId", "campaignId", "country"),
    "source_bids": ("campaignSetId", "campaignId", "country", "sourceAppId"),
}

ENDPOINTS = (*UNITY_ADS_ENDPOINTS, *MANAGEMENT_PRIMARY_KEYS)
# SKAN is opt-in to leave room for retries in the shared stats quota.
SYNC_DEFAULTS = dict.fromkeys((*MANAGEMENT_PRIMARY_KEYS, "skan_daily"), False)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [_TIMESTAMP] for name in UNITY_ADS_ENDPOINTS}

LOOKBACK: dict[str, int] = dict.fromkeys(UNITY_ADS_ENDPOINTS, LOOKBACK_SECONDS)

# The stats tables read the last 30 days again on each sync. Appending would duplicate those rows.
MERGE_ONLY = tuple(UNITY_ADS_ENDPOINTS)
