from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DAILY_REPORT = "daily_report"
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

ENDPOINTS: tuple[str, ...] = (DAILY_REPORT, *LOOKUPS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    DAILY_REPORT: [incremental_field(DATE_FIELD, IncrementalFieldType.Date)],
}

DESCRIPTIONS: dict[str, str] = {
    DAILY_REPORT: "Daily campaign statistics, one row per day and combination of the dimensions you chose.",
    "custom_dimensions": "The custom dimensions defined in your Singular account.",
    "cohort_metrics": "The cohort metrics and events you can add to a report.",
    "conversion_metrics": "The conversion events you can add to a report as metrics.",
}
