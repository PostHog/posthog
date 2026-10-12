from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Clarity's Data Export API always returns every metric type (Traffic, ScrollDepth, EngagementTime,
# PopularPages, dead/rage/quickback/error clicks, ScriptErrorCount, ...) in a single response — there
# is no per-metric filter — so the whole payload is modeled as one always-available table.
ENDPOINT_NAME = "project_live_insights"
ENDPOINTS = (ENDPOINT_NAME,)

# Sentinel value for an unset breakdown-dimension select field.
NO_DIMENSION = "none"

# Exact dimension labels the API expects (case-sensitive), per the Clarity Data Export API docs.
DIMENSION_OPTIONS: tuple[str, ...] = (
    "Browser",
    "Device",
    "Country/Region",
    "OS",
    "Source",
    "Medium",
    "Campaign",
    "Channel",
    "URL",
)

NUM_OF_DAYS_OPTIONS: tuple[str, ...] = ("1", "2", "3")
DEFAULT_NUM_OF_DAYS = "1"

# The API has no server-side "since"/"updated after" filter: `numOfDays` is a fixed rolling window
# relative to the call, not a resumable cursor. `synced_at` is a client-captured timestamp so that
# recurring syncs append daily snapshots (accumulating history downstream) instead of overwriting
# the same rows — it is not pushed down to the API as a filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ENDPOINT_NAME: [
        {
            "label": "Synced at",
            "type": IncrementalFieldType.DateTime,
            "field": "synced_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

# Append-only: the API can only return the last 1-3 days (aggregated as of the call), so there is no
# stable, reusable primary key to merge on across syncs — every sync's rows are new snapshot rows.
APPEND_ONLY_ENDPOINTS = frozenset({ENDPOINT_NAME})
