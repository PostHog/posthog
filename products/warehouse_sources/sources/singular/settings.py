from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen, incremental_field

DAILY_REPORT = "daily_report"
SKADNETWORK_REPORT = "skadnetwork_report"
SKADNETWORK_RAW_REPORT = "skadnetwork_raw_report"
AD_MONETIZATION_REPORT = "ad_monetization_report"
FILTERS = "filters"
# Singular's report rows carry the day as `start_date`/`end_date`. The source adds one `date`
# column per row so the cursor and the primary key do not depend on that shape.
DATE_FIELD = "date"

# Network data is the one report type every Singular account can query, so the defaults work for
# an account that has no attribution tracker set up.
DEFAULT_DIMENSIONS: tuple[str, ...] = (
    "app",
    "source",
    "os",
    "country_field",
    "adn_campaign_id",
    "adn_campaign_name",
)
DEFAULT_METRICS: tuple[str, ...] = ("adn_cost", "adn_impressions", "adn_clicks", "adn_installs")

# A first sync reads this many days. Each day is one report, and every row counts against the
# account's daily row quota, so a deeper default would fail the first sync of a large account.
HISTORY_DAYS = 30
# Networks restate recent days. Singular recommends re-reading 7 days of network data on each pull.
REPORT_LOOKBACK_SECONDS = 7 * 24 * 60 * 60


@frozen
class SingularLookupConfig:
    """One discovery endpoint that returns a complete list in a single response."""

    path: str
    data_key: str
    primary_key: str


LOOKUPS: dict[str, SingularLookupConfig] = {
    "custom_dimensions": SingularLookupConfig(
        path="/api/custom_dimensions", data_key="custom_dimensions", primary_key="id"
    ),
    "cohort_metrics": SingularLookupConfig(path="/api/cohort_metrics", data_key="metrics", primary_key="name"),
    "conversion_metrics": SingularLookupConfig(path="/api/conversion_metrics", data_key="metrics", primary_key="name"),
}

FILTERS_PATH = "/api/{api_version}/reporting/filters"


@frozen
class SingularFixedReportConfig:
    """A report with a fixed field list, read one day at a time like `daily_report`."""

    path: str
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    params: tuple[tuple[str, str], ...] = ()
    # The SKAdNetwork reports run through the async create/status/download flow. Ad monetization
    # answers the GET itself.
    is_async: bool = True


FIXED_REPORTS: dict[str, SingularFixedReportConfig] = {
    SKADNETWORK_REPORT: SingularFixedReportConfig(
        path="/api/{api_version}/create_async_skadnetwork_report",
        dimensions=("app", "source", "country_field", "unified_campaign_id", "unified_campaign_name"),
        metrics=(
            "adn_cost",
            "skan_report_network_impressions",
            "skan_report_network_clicks",
            "skan_installs",
            "tracker_installs",
            "skan_ecpi",
            "skan_revenue",
        ),
        # Postback dates do not move once Apple has sent the postback, unlike Singular's estimated install date.
        params=(("skadnetwork_date_type", "skan_postback_date"),),
    ),
    SKADNETWORK_RAW_REPORT: SingularFixedReportConfig(
        path="/api/{api_version}/create_async_skadnetwork_raw_report",
        dimensions=(
            "app",
            "source",
            "skan_app_id",
            "skan_network_id",
            "skan_campaign_id",
            "skan_publisher_id",
            "skan_conversion_value",
            "skan_redownloads",
            "skan_validated",
            "country_field",
        ),
        metrics=("skan_installs",),
        params=(("skadnetwork_date_type", "skan_postback_date"),),
    ),
    AD_MONETIZATION_REPORT: SingularFixedReportConfig(
        path="/api/{api_version}/admonetization/reporting",
        dimensions=("app", "source", "os", "ad_country", "ad_type_name"),
        metrics=(
            "ad_requests",
            "filled_ad_requests",
            "ad_fill_rate",
            "ad_impressions",
            "ad_clicks",
            "ad_revenue",
            "ad_ecpm",
        ),
        is_async=False,
    ),
}

REPORTS: tuple[str, ...] = (DAILY_REPORT, *FIXED_REPORTS)
ENDPOINTS: tuple[str, ...] = (*REPORTS, FILTERS, *LOOKUPS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    report: [incremental_field(DATE_FIELD, IncrementalFieldType.Date)] for report in REPORTS
}

DESCRIPTIONS: dict[str, str] = {
    DAILY_REPORT: "Daily campaign statistics, one row per day and combination of the dimensions you chose.",
    SKADNETWORK_REPORT: "Daily SKAdNetwork installs combined with ad network cost, clicks, and impressions, by app, source, country, and campaign. Needs the Singular attribution tracker.",
    SKADNETWORK_RAW_REPORT: "Daily SKAdNetwork install counts from raw postbacks, by app, network, SKAdNetwork IDs, and conversion value. Needs the Singular attribution tracker.",
    AD_MONETIZATION_REPORT: "Daily ad revenue, requests, fill rate, and impressions from your monetization networks. Needs ad monetization reporting set up in Singular.",
    FILTERS: "The values each report dimension can take, such as the OS and source codes, with their display names.",
    "custom_dimensions": "The custom dimensions defined in your Singular account.",
    "cohort_metrics": "The cohort metrics and events you can add to a report.",
    "conversion_metrics": "The conversion events you can add to a report as metrics.",
}
