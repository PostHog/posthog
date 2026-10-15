from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Both APIs are regional. The service name doubles as the botocore model name, the SigV4 signing
# name and the endpoint prefix (`logs.<region>.amazonaws.com`, `monitoring.<region>.amazonaws.com`).
AwsService = Literal["logs", "monitoring"]

LOGS_SERVICE: AwsService = "logs"
MONITORING_SERVICE: AwsService = "monitoring"
MONITORING_MODEL_NAME = "cloudwatch"
MONITORING_API_VERSION = "2010-08-01"
LOGS_API_VERSION = "2014-03-28"

# FilterLogEvents caps a page at 10,000 events or 1 MB. DescribeLogGroups caps at 50.
LOG_EVENTS_PAGE_SIZE = 10_000
LOG_GROUPS_PAGE_SIZE = 50
# DescribeAlarms and DescribeAlarmHistory cap at 100 records.
ALARMS_PAGE_SIZE = 100
# GetMetricData returns up to 100,800 datapoints per call before it needs a NextToken.
METRIC_DATA_MAX_DATAPOINTS = 100_800
# Log groups discovered when the user names none. Beyond this a user should list the groups.
MAX_DISCOVERED_LOG_GROUPS = 50


@dataclass(frozen=True)
class CloudWatchEndpointConfig:
    name: str
    service: AwsService
    operation: str
    primary_key: list[str]
    # Days before today a first sync reaches back. Logs and metrics are high volume, so these
    # stay short; a user who wants more sets a start date on the source.
    lookback_days: int | None = None
    # Days covered by one request series. GetMetricData degrades to coarser datapoints the
    # further back it reads, and both time-bound operations paginate within the window.
    window_days: int | None = None
    partition_key: str | None = None
    partition_format: Literal["month", "week", "day", "hour"] | None = None
    # Whether rows arrive in ascending timestamp order across the whole run. Log events are read
    # per log group and metric values per query, so neither is globally ordered.
    sorted_ascending: bool = False


AMAZON_CLOUDWATCH_ENDPOINTS: dict[str, CloudWatchEndpointConfig] = {
    "log_groups": CloudWatchEndpointConfig(
        name="log_groups",
        service=LOGS_SERVICE,
        operation="DescribeLogGroups",
        primary_key=["log_group_name"],
    ),
    "log_events": CloudWatchEndpointConfig(
        name="log_events",
        service=LOGS_SERVICE,
        operation="FilterLogEvents",
        primary_key=["log_group_name", "event_id"],
        lookback_days=7,
        partition_key="timestamp",
        partition_format="day",
    ),
    "alarms": CloudWatchEndpointConfig(
        name="alarms",
        service=MONITORING_SERVICE,
        operation="DescribeAlarms",
        primary_key=["alarm_arn"],
    ),
    "alarm_history": CloudWatchEndpointConfig(
        name="alarm_history",
        service=MONITORING_SERVICE,
        operation="DescribeAlarmHistory",
        # A history item has no id. An alarm records one item per type per instant.
        primary_key=["alarm_name", "timestamp", "history_item_type"],
        # CloudWatch keeps alarm history for 30 days.
        lookback_days=30,
        partition_key="timestamp",
        partition_format="month",
        sorted_ascending=True,
    ),
    "metric_data": CloudWatchEndpointConfig(
        name="metric_data",
        service=MONITORING_SERVICE,
        operation="GetMetricData",
        primary_key=["query_id", "timestamp"],
        # One-minute datapoints are kept for 15 days; older reads come back at 5-minute resolution.
        lookback_days=14,
        window_days=14,
        partition_key="timestamp",
        partition_format="day",
    ),
}

ENDPOINTS = tuple(AMAZON_CLOUDWATCH_ENDPOINTS.keys())

# Every time-bound operation filters server-side on the event timestamp, so that is the cursor.
# Log groups and alarms are catalogs with no time filter and stay full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, endpoint_config in AMAZON_CLOUDWATCH_ENDPOINTS.items()
    if endpoint_config.lookback_days is not None
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "log_groups": "Log groups in the region, with retention, stored bytes and encryption settings.",
    "log_events": "Log events from the configured log groups (or every log group when none is set), one row per event.",
    "alarms": "Metric and composite alarms with their current state, thresholds and actions.",
    "alarm_history": "State transitions, configuration updates and action executions for every alarm.",
    "metric_data": "Datapoints for the metric queries configured on the source, one row per query and timestamp.",
}
