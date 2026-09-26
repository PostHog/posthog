from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Hostname segment in https://api-{dc}.moengage.com. The config value is interpolated into the
# host, so it must come from this allowlist: a crafted value like "01.evil.com" would otherwise
# retarget the Basic Auth credential at an attacker-controlled host.
MOENGAGE_DATA_CENTERS = ("01", "02", "03", "04", "05", "06", "101")

# Documented page maximums: campaign search serves up to 15 campaigns per page, campaign-stats up
# to 10 campaigns per page.
SEARCH_PAGE_SIZE = 15
STATS_PAGE_SIZE = 10

# The campaign-stats API rejects a start_date..end_date span wider than 30 days, so the aggregate
# campaign_report snapshot asks for exactly that trailing window.
REPORT_WINDOW_DAYS = 30

# Full-refresh floor for the daily report's day-by-day fan-out when the user sets no start date.
# Each day costs one request set against a 100-requests-per-minute workspace limit, so an
# unbounded backfill is not the default.
DEFAULT_BACKFILL_DAYS = 90

# Conversion metrics for a day keep restating as attributions land, so each incremental run
# re-pulls a trailing window; merge dedupes the overlap on the synthesized `id`.
DAILY_REPORT_LOOKBACK_SECONDS = 60 * 60 * 24 * 3

# Fixed report dimensions. The stats API requires both on every request; TOTAL_CONVERSIONS and
# TOTAL are the widest documented options, so the synced numbers match the dashboard's defaults.
ATTRIBUTION_TYPE = "TOTAL_CONVERSIONS"
METRIC_TYPE = "TOTAL"


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@frozen
class MoEngageEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    partition_key: str | None = None
    # True only for the daily report, whose date window is a genuine server-side filter. The
    # campaign list only filters on created_date, which would freeze status changes on old
    # campaigns, so it stays full-refresh; the aggregate report restates wholesale every sync.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_lookback_seconds: int | None = None


MOENGAGE_ENDPOINTS: dict[str, MoEngageEndpointConfig] = {
    "campaigns": MoEngageEndpointConfig(
        name="campaigns",
        path="/v5/campaigns/search",
        # With campaign versioning enabled each published revision is its own document with its own
        # `id`; `campaign_id` stays the stable cross-version identifier and is kept as a column.
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "campaign_report": MoEngageEndpointConfig(
        name="campaign_report",
        path="/core-services/v1/campaign-stats",
        primary_keys=["id"],
    ),
    "daily_campaign_report": MoEngageEndpointConfig(
        name="daily_campaign_report",
        path="/core-services/v1/campaign-stats",
        primary_keys=["id"],
        partition_key="date",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("date")],
        default_incremental_lookback_seconds=DAILY_REPORT_LOOKBACK_SECONDS,
    ),
}

ENDPOINTS = tuple(MOENGAGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MOENGAGE_ENDPOINTS.items()
}
