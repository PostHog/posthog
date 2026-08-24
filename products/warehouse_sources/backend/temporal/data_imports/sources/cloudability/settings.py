from products.warehouse_sources.backend.types import IncrementalField

# Cloudability's v3 API is REST/JSON, authenticated with an API key sent as the HTTP Basic
# username (empty password). None of these endpoints expose a server-side "modified since"
# filter, so every table is full refresh — see cloudability.py for how each one is queried.
ENDPOINTS = (
    "Costs",
    "Views",
    "BusinessMappingDimensions",
    "BusinessMappingMetrics",
    "Anomalies",
)

# No endpoint documents a reliable incremental cursor: cost rows are a dimension-grouped
# aggregate over a queried date window (no per-row id/timestamp survives the group-by), and the
# entity endpoints (views, business mappings, anomalies) don't expose an updated-since filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

PRIMARY_KEYS: dict[str, list[str]] = {
    # No id survives the dimension group-by on a cost report row; the dimension values
    # queried together are what uniquely identifies a row for the window synced.
    "Costs": ["vendor", "linked_account_name", "region", "enhanced_service_name"],
    "Views": ["id"],
    "BusinessMappingDimensions": ["name"],
    "BusinessMappingMetrics": ["name"],
    "Anomalies": ["id"],
}

# Dimensions and metrics for the Costs report, taken from the worked examples on Cloudability's
# own "Cost Reporting End Point" doc (not guessed) — the endpoint accepts up to 15 dimensions and
# 8 metrics, but a source can't ask the user to pick per-sync, so this is a sensible fixed set.
COST_REPORT_DIMENSIONS = ("vendor", "linked_account_name", "region", "enhanced_service_name")
COST_REPORT_METRICS = ("unblended_cost", "total_amortized_cost", "usage_hours")

# Cost data is restated for weeks after the fact as vendor invoices settle, and the report has no
# per-row date dimension to merge on incrementally, so each sync re-queries and replaces this
# trailing window rather than trying to accumulate history additively.
COST_REPORT_LOOKBACK_DAYS = 395

# Anomalies are queried over a trailing window and fully replaced each sync, since the API only
# supports "detected between startDate and endDate" rather than an updated-since filter.
ANOMALIES_LOOKBACK_DAYS = 90
