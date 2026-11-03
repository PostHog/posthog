from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

UNITY_STATS_URL = (
    "https://services.api.unity.com/advertise/stats/v2/organizations/{organization_id}/reports/acquisitions"
)

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
    name: str
    breakdowns: tuple[str, ...]
    primary_keys: tuple[str, ...]
    # Days per request. Both tables share Unity's quota of 30 requests per 30 minutes, so a first sync
    # of both (16 requests for a year) fits inside one quota window. Unity also counts the quota per IP
    # address, which other accounts syncing from the same workers share, so a 429 is still possible.
    # It fails the attempt, and the retry resumes at the saved window.
    window_days: int


UNITY_ADS_ENDPOINTS: dict[str, UnityAdsEndpointConfig] = {
    "campaigns_daily": UnityAdsEndpointConfig(
        name="campaigns_daily",
        breakdowns=("campaign",),
        primary_keys=("timestamp", "campaignId"),
        window_days=92,
    ),
    "campaigns_daily_by_country": UnityAdsEndpointConfig(
        name="campaigns_daily_by_country",
        breakdowns=("campaign", "country"),
        primary_keys=("timestamp", "campaignId", "country"),
        window_days=31,
    ),
}

ENDPOINTS = tuple(UNITY_ADS_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [_TIMESTAMP] for name in UNITY_ADS_ENDPOINTS}

LOOKBACK: dict[str, int] = dict.fromkeys(UNITY_ADS_ENDPOINTS, LOOKBACK_SECONDS)

# Both tables re-read the last 30 days each run. Appending would write those rows again.
MERGE_ONLY = tuple(UNITY_ADS_ENDPOINTS)
