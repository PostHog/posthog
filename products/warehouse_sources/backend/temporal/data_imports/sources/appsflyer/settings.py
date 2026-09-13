from dataclasses import field
from enum import StrEnum

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]

_EVENT_TIME_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "event_time",
        "type": IncrementalFieldType.DateTime,
        "field": "event_time",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_INSTALL_TIME_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "install_time",
        "type": IncrementalFieldType.Date,
        "field": "install_time",
        "field_type": IncrementalFieldType.Date,
    },
]


class AppsFlyerReportKind(StrEnum):
    """Which Pull API serves a report. Each one has its own path, date window and row limits."""

    AGGREGATE = "aggregate"
    RAW = "raw"
    MASTER = "master"


# The Master API needs both groupings and kpis. The groupings mirror the aggregate reports'
# dimensions so the two line up; the KPIs are the documented generic LTV set, because the
# pattern KPIs (cohort_*, retention_*, event_counter_*) depend on the account's package and a
# single unavailable KPI fails the whole report.
_MASTER_GROUPINGS = ("install_time", "af_prt", "pid", "c", "geo")
_MASTER_KPIS = (
    "impressions",
    "clicks",
    "installs",
    "cr",
    "sessions",
    "loyal_users",
    "loyal_users_rate",
    "cost",
    "revenue",
    "roi",
    "arpu_ltv",
    "average_ecpi",
    "uninstalls",
    "uninstalls_rate",
)

# Ad revenue's monetization columns are additional fields, so ask for them by name: they carry the
# grain AppsFlyer aggregates device-level ad revenue on, which is what the row key needs.
_AD_REVENUE_ADDITIONAL_FIELDS = ("monetization_network", "ad_unit", "placement", "impressions")

_RAW_EVENT_PRIMARY_KEYS = ["appsflyer_id", "event_time"]
_AD_REVENUE_PRIMARY_KEYS = [*_RAW_EVENT_PRIMARY_KEYS, "monetization_network", "ad_unit", "placement"]


@frozen
class AppsFlyerEndpointConfig:
    name: str
    # Report slug in the Pull API path. Empty for the Master API, whose path carries no slug.
    report: str = ""
    kind: AppsFlyerReportKind = AppsFlyerReportKind.AGGREGATE
    # Aggregate reports have no row ids; the dimension columns (normalized
    # headers) form the key, and collisions are tolerated via the duplicate-pk
    # flag.
    primary_keys: list[str] = field(
        default_factory=lambda: ["date", "agency_pmd_af_prt", "media_source_pid", "campaign_c"]
    )
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DATE_INCREMENTAL_FIELDS))
    partition_key: str = "date"
    partition_format: PartitionFormat = "month"
    # Query params sent on every request for this report, on top of the date window.
    extra_params: dict[str, str] = field(default_factory=dict)


# AppsFlyer's aggregate Pull API returns CSV per date window (max ~1000 days);
# headers are normalized to snake_case columns. The raw-data Pull API returns
# event-level CSV rows over a 90-day window, and the Master API returns one
# aggregate LTV report per 31-day window.
APPSFLYER_ENDPOINTS: dict[str, AppsFlyerEndpointConfig] = {
    "daily_report": AppsFlyerEndpointConfig(
        name="daily_report",
        report="daily_report",
    ),
    "geo_report": AppsFlyerEndpointConfig(
        name="geo_report",
        report="geo_by_date_report",
        primary_keys=["date", "agency_pmd_af_prt", "media_source_pid", "campaign_c", "country"],
    ),
    "partners_report": AppsFlyerEndpointConfig(
        name="partners_report",
        report="partners_by_date_report",
    ),
    "installs": AppsFlyerEndpointConfig(
        name="installs",
        report="installs_report",
        kind=AppsFlyerReportKind.RAW,
        primary_keys=list(_RAW_EVENT_PRIMARY_KEYS),
        incremental_fields=list(_EVENT_TIME_INCREMENTAL_FIELDS),
        partition_key="event_time",
        partition_format="day",
    ),
    "in_app_events": AppsFlyerEndpointConfig(
        name="in_app_events",
        report="in_app_events_report",
        kind=AppsFlyerReportKind.RAW,
        primary_keys=[*_RAW_EVENT_PRIMARY_KEYS, "event_name"],
        incremental_fields=list(_EVENT_TIME_INCREMENTAL_FIELDS),
        partition_key="event_time",
        partition_format="day",
    ),
    "ad_revenue": AppsFlyerEndpointConfig(
        name="ad_revenue",
        report="ad_revenue_raw",
        kind=AppsFlyerReportKind.RAW,
        primary_keys=list(_AD_REVENUE_PRIMARY_KEYS),
        incremental_fields=list(_EVENT_TIME_INCREMENTAL_FIELDS),
        partition_key="event_time",
        partition_format="day",
        extra_params={"additional_fields": ",".join(_AD_REVENUE_ADDITIONAL_FIELDS)},
    ),
    "ad_revenue_organic": AppsFlyerEndpointConfig(
        name="ad_revenue_organic",
        report="ad_revenue_organic_raw",
        kind=AppsFlyerReportKind.RAW,
        primary_keys=list(_AD_REVENUE_PRIMARY_KEYS),
        incremental_fields=list(_EVENT_TIME_INCREMENTAL_FIELDS),
        partition_key="event_time",
        partition_format="day",
        extra_params={"additional_fields": ",".join(_AD_REVENUE_ADDITIONAL_FIELDS)},
    ),
    "ad_revenue_retargeting": AppsFlyerEndpointConfig(
        name="ad_revenue_retargeting",
        report="ad-revenue-raw-retarget",
        kind=AppsFlyerReportKind.RAW,
        primary_keys=list(_AD_REVENUE_PRIMARY_KEYS),
        incremental_fields=list(_EVENT_TIME_INCREMENTAL_FIELDS),
        partition_key="event_time",
        partition_format="day",
        extra_params={"additional_fields": ",".join(_AD_REVENUE_ADDITIONAL_FIELDS)},
    ),
    "master_report": AppsFlyerEndpointConfig(
        name="master_report",
        kind=AppsFlyerReportKind.MASTER,
        primary_keys=["install_time", "agency_pmd_af_prt", "media_source_pid", "campaign_c", "country"],
        incremental_fields=list(_INSTALL_TIME_INCREMENTAL_FIELDS),
        partition_key="install_time",
        extra_params={
            "groupings": ",".join(_MASTER_GROUPINGS),
            "kpis": ",".join(_MASTER_KPIS),
        },
    ),
}

ENDPOINTS = tuple(APPSFLYER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPSFLYER_ENDPOINTS.items() if config.incremental_fields
}
