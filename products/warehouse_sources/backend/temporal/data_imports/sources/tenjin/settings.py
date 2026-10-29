from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every report is requested at daily granularity, so `date` is present on every row. It is the
# only stable cursor the Reporting Metrics API exposes (it filters server-side via the required
# start_date/end_date params).
_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]

# Tenjin's documented default metric set per report endpoint. Pinned here instead of relying on
# the server default so the table schema stays stable if Tenjin changes its defaults.
_SPEND_METRICS = "spend,impressions,clicks,installs,cpi,ctr,cvr,tcpi,tracked_installs"
_AD_REVENUE_METRICS = "ad_revenue,clicks,impressions,ecpm,ecpc"
_SK_AD_NETWORK_METRICS = "conversion_value_avg,conversion_value_count,conversion_value_total"
# Spend and installs give the cohort size and cost; the N-day metrics follow that install cohort.
_COHORT_DAYS = (1, 7, 30)
_COHORT_METRICS = ",".join(
    [
        "spend",
        "installs",
        *(
            f"{metric}_{days}d"
            for days in _COHORT_DAYS
            for metric in ("users", "sessions", "retention", "revenues", "total_rev", "roas")
        ),
    ]
)

# Tenjin keeps restating recent days (late SKAN postbacks, ad network cost corrections), so an
# incremental run re-reads a trailing window; the merge dedupes on the dimension key.
DEFAULT_LOOKBACK_DAYS = 7


@frozen
class TenjinReportConfig:
    name: str
    path: str
    # Sent verbatim as the `group_by` / `metrics` query params. Together they define the report's
    # column set, so changing either changes the table schema for every connected team.
    group_by: str
    metrics: str
    # Aggregated report rows have no row ids; the date plus the grouping dimensions are the
    # natural key. Every key column must be a field the chosen group_by returns.
    primary_keys: list[str]
    description: str
    lookback_days: int = DEFAULT_LOOKBACK_DAYS


# One entry per report shape we expose. Each Reporting Metrics endpoint is a single report whose
# response schema is defined by the requested group_by and metrics, so each "table" here is a
# fixed dimension/metric selection rather than a distinct collection.
TENJIN_REPORTS: dict[str, TenjinReportConfig] = {
    "app_report": TenjinReportConfig(
        name="app_report",
        path="/reports/spend",
        group_by="app",
        metrics=_SPEND_METRICS,
        primary_keys=["date", "app_id"],
        description="Daily user-acquisition performance per app: spend, impressions, clicks, installs, and conversion metrics.",
    ),
    "campaign_report": TenjinReportConfig(
        name="campaign_report",
        path="/reports/spend",
        group_by="campaign",
        metrics=_SPEND_METRICS,
        # Grouping by campaign includes the app and channel in the response, so campaign_id is
        # the only grouping dimension needed alongside the date.
        primary_keys=["date", "campaign_id"],
        description="Daily user-acquisition performance per campaign, including the campaign's app and channel.",
    ),
    "ad_revenue_report": TenjinReportConfig(
        name="ad_revenue_report",
        path="/reports/ad_revenue",
        group_by="channel,app",
        metrics=_AD_REVENUE_METRICS,
        primary_keys=["date", "app_id", "ad_network_id"],
        description="Daily ad monetization revenue per app broken down by channel: ad revenue, impressions, clicks, eCPM, and eCPC.",
    ),
    "sk_ad_network_report": TenjinReportConfig(
        name="sk_ad_network_report",
        path="/reports/sk_ad_network",
        # Tenjin's documented example grouping for SKAN pulls. The response also carries the
        # campaign, SKAdNetwork id, and fidelity type for these rows, which is why they are part
        # of the key below.
        group_by="app,channel,sk_campaign,sk_source_app,conversion_value",
        metrics=_SK_AD_NETWORK_METRICS,
        primary_keys=[
            "date",
            "app_id",
            "ad_network_id",
            "sk_ad_network_id",
            "sk_campaign_id",
            "sk_source_app_id",
            "fidelity_type",
            "conversion_value",
        ],
        description="Daily SKAdNetwork postback aggregates per app, channel, SKAN campaign, source app, and conversion value (iOS only).",
    ),
    "campaign_cohort_report": TenjinReportConfig(
        name="campaign_cohort_report",
        path="/reports/spend",
        group_by="campaign",
        metrics=_COHORT_METRICS,
        primary_keys=["date", "campaign_id"],
        description="Daily install cohorts per campaign: retained users, sessions, retention rate, revenue, and ROAS at day 1, 7, and 30.",
        # A cohort's day-30 metrics keep changing for 30 days after its install date.
        lookback_days=max(_COHORT_DAYS) + DEFAULT_LOOKBACK_DAYS,
    ),
    "campaign_country_report": TenjinReportConfig(
        name="campaign_country_report",
        path="/reports/spend",
        group_by="campaign,country",
        metrics=_SPEND_METRICS,
        primary_keys=["date", "campaign_id", "country"],
        description="Daily user-acquisition performance per campaign and country, including the campaign's app and channel.",
    ),
    "ad_placement_report": TenjinReportConfig(
        name="ad_placement_report",
        path="/reports/ad_revenue",
        group_by="ad_placement",
        metrics=_AD_REVENUE_METRICS,
        # Tenjin documents ad_placement_id as a UUID but not whether it is unique across apps and
        # channels, so the app and channel it belongs to are part of the key too.
        primary_keys=["date", "app_id", "ad_network_id", "ad_placement_id"],
        description="Daily ad monetization revenue per ad placement, including the placement's app and channel.",
    ),
}

ENDPOINTS = tuple(TENJIN_REPORTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(_DATE_INCREMENTAL_FIELDS) for name in TENJIN_REPORTS
}

DESCRIPTIONS: dict[str, str] = {name: config.description for name, config in TENJIN_REPORTS.items()}
