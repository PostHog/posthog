from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://monitoring.googleapis.com/v3"

# `monitoring.read` is the narrowest scope that serves every endpoint this source calls.
SCOPES = ["https://www.googleapis.com/auth/monitoring.read"]

METRIC_DESCRIPTORS = "MetricDescriptors"
MONITORED_RESOURCE_DESCRIPTORS = "MonitoredResourceDescriptors"
TIME_SERIES = "TimeSeries"

ENDPOINTS = (METRIC_DESCRIPTORS, MONITORED_RESOURCE_DESCRIPTORS, TIME_SERIES)

# Cloud Monitoring returns a series' points newest first, so the transport sorts each window
# before yielding it. A bounded window is what keeps that sort in memory.
WINDOW_HOURS = 24

# Cloud Monitoring keeps most metrics for 6 weeks, so a longer first sync just returns nothing.
INITIAL_BACKFILL_DAYS = 40

# Points can arrive late, and an aligned point is only final once its alignment period closes.
INCREMENTAL_LOOKBACK_SECONDS = 2 * 60 * 60

PAGE_SIZE = 10000

PRIMARY_KEYS: dict[str, list[str]] = {
    METRIC_DESCRIPTORS: ["name"],
    MONITORED_RESOURCE_DESCRIPTORS: ["name"],
    # One series produces at most one point per interval end, so this identifies a row.
    TIME_SERIES: ["series_key", "point_end_time"],
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TIME_SERIES: [
        {
            "label": "point_end_time",
            "type": IncrementalFieldType.DateTime,
            "field": "point_end_time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

DESCRIPTIONS = {
    METRIC_DESCRIPTORS: "Every metric type the project exposes, with its kind, value type and labels.",
    MONITORED_RESOURCE_DESCRIPTORS: "Every monitored resource type the project exposes, with its labels.",
    TIME_SERIES: "Metric points matching the configured monitoring filter, one row per series and interval.",
}
