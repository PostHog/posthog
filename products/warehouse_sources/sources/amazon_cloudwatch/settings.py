from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# All three APIs are regional. The service name doubles as the SigV4 signing name and the endpoint
# prefix (`logs.<region>.amazonaws.com`, `monitoring.<region>.amazonaws.com`, `sts.<region>...`).
AwsService = Literal["logs", "monitoring", "sts"]

LOGS_SERVICE: AwsService = "logs"
MONITORING_SERVICE: AwsService = "monitoring"
STS_SERVICE: AwsService = "sts"
# botocore model name and API version of each service, pinned so a botocore upgrade cannot change them.
SERVICE_MODELS: dict[AwsService, tuple[str, str]] = {
    LOGS_SERVICE: ("logs", "2014-03-28"),
    MONITORING_SERVICE: ("cloudwatch", "2010-08-01"),
    STS_SERVICE: ("sts", "2011-06-15"),
}

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
    # Seconds an incremental run re-reads behind its watermark, for rows that arrive late. The
    # merge key drops the rows read twice.
    incremental_lookback_seconds: int | None = None
    # `desc` makes the pipeline commit the highest timestamp only when the run completes. Log events
    # arrive per log group and datapoints per query, so neither is ordered across the run.
    sort_mode: Literal["asc", "desc"] = "asc"


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
        # CloudWatch Logs accepts events stamped in the past, and filters on that event time.
        incremental_lookback_seconds=3600,
        partition_key="timestamp",
        partition_format="day",
        sort_mode="desc",
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
        # A history item has no id, and an alarm with contributors records several items per instant,
        # so the key is a hash of the whole item.
        primary_key=["history_id"],
        # CloudWatch keeps alarm history for 30 days.
        lookback_days=30,
        partition_key="timestamp",
        partition_format="month",
    ),
    "metric_data": CloudWatchEndpointConfig(
        name="metric_data",
        service=MONITORING_SERVICE,
        operation="GetMetricData",
        primary_key=["query_id", "label", "timestamp"],
        # One-minute datapoints are kept for 15 days; older reads come back at 5-minute resolution.
        lookback_days=14,
        window_days=14,
        # Recent datapoints are still being aggregated, and some services publish minutes late.
        incremental_lookback_seconds=3600,
        partition_key="timestamp",
        partition_format="day",
        sort_mode="desc",
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
