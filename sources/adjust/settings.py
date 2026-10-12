from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every report is grouped by `day`, which is the only stable cursor the Report Service API
# exposes (it filters server-side via `date_period`).
_DAY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "day",
        "type": IncrementalFieldType.Date,
        "field": "day",
        "field_type": IncrementalFieldType.Date,
    },
]

# Delivery + engagement metrics available on every Adjust account. Cost and revenue metrics
# return 0 until the account has ad-spend / revenue integrations configured, which is a
# reporting setup concern rather than a request error.
_CORE_METRICS = [
    "impressions",
    "clicks",
    "installs",
    "sessions",
    "reattributions",
    "click_conversion_rate",
    "impression_conversion_rate",
    "cost",
    "ecpi",
    "revenue",
]

# Active-user metrics only make sense at app grain — they are not additive across campaign,
# creative, or country breakdowns, so they stay on the app-level reports.
_USER_METRICS = ["daus", "waus", "maus"]


@dataclass
class AdjustReportConfig:
    name: str
    # `dimensions` / `metrics` are sent verbatim as the Report Service API's comma-separated
    # `dimensions` and `metrics` params, and they define the report's column set.
    dimensions: list[str]
    metrics: list[str] = field(default_factory=lambda: list(_CORE_METRICS))
    # Aggregated reports have no row ids — the requested dimensions are the natural key. Blank
    # dimension values (e.g. an unattributed campaign) can collide; the merge's per-batch dedup
    # (keep-last-per-key) resolves that safely, so incremental syncing stays available.
    primary_keys: list[str] = field(default_factory=lambda: ["day", "app_token"])
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DAY_INCREMENTAL_FIELDS))
    description: str | None = None


# One entry per report shape we expose. Adjust's Report Service API is a single endpoint whose
# response schema is defined entirely by the requested dimensions and metrics, so each "table"
# here is a fixed dimension/metric selection rather than a distinct URL.
ADJUST_REPORTS: dict[str, AdjustReportConfig] = {
    "daily_report": AdjustReportConfig(
        name="daily_report",
        dimensions=["day", "app", "app_token"],
        metrics=[*_CORE_METRICS, *_USER_METRICS],
        description="Daily performance per app — installs, sessions, clicks, impressions, cost, revenue, and active users.",
    ),
    "partner_report": AdjustReportConfig(
        name="partner_report",
        dimensions=["day", "app", "app_token", "partner_name"],
        primary_keys=["day", "app_token", "partner_name"],
        description="Daily performance per app broken down by attribution partner (network).",
    ),
    "campaign_report": AdjustReportConfig(
        name="campaign_report",
        dimensions=["day", "app", "app_token", "partner_name", "campaign", "campaign_id_network"],
        primary_keys=["day", "app_token", "partner_name", "campaign", "campaign_id_network"],
        description="Daily performance per campaign, broken down by attribution partner.",
    ),
    "creative_report": AdjustReportConfig(
        name="creative_report",
        dimensions=["day", "app", "app_token", "partner_name", "campaign", "adgroup", "creative"],
        primary_keys=["day", "app_token", "partner_name", "campaign", "adgroup", "creative"],
        description="Daily performance per creative, broken down by ad group, campaign, and attribution partner.",
    ),
    "country_report": AdjustReportConfig(
        name="country_report",
        dimensions=["day", "app", "app_token", "country", "country_code"],
        primary_keys=["day", "app_token", "country_code"],
        description="Daily performance per app broken down by country.",
    ),
    "os_report": AdjustReportConfig(
        name="os_report",
        dimensions=["day", "app", "app_token", "os_name"],
        metrics=[*_CORE_METRICS, *_USER_METRICS],
        primary_keys=["day", "app_token", "os_name"],
        description="Daily performance per app broken down by operating system.",
    ),
}

ENDPOINTS = tuple(ADJUST_REPORTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ADJUST_REPORTS.items() if config.incremental_fields
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in ADJUST_REPORTS.items() if config.description
}
