from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

CLOUDTRAIL_API_VERSION = "2013-11-01"
TARGET_PREFIXES = {CLOUDTRAIL_API_VERSION: "com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101"}
LOOKBACK_SECONDS = 90 * 24 * 60 * 60
LAKE_QUERY_HISTORY_SECONDS = 7 * 24 * 60 * 60
# Lake queries still running at sync time are read again on the next sync so their final status lands.
LAKE_QUERY_REFRESH_SECONDS = 24 * 60 * 60
# Hourly points are the only granularity CloudTrail keeps for the full 90 days of Insights metrics.
INSIGHTS_METRIC_PERIOD_SECONDS = 3600


@frozen
class CloudTrailEndpoint:
    operation: str
    result_key: str
    primary_key: tuple[str, ...]
    page_size: int | None = None
    event_category: str | None = None
    timestamps: tuple[str, ...] = ()
    incremental_field: str | None = None
    partition_key: str | None = None
    # Fan-out endpoints read one parent listing per run and call `operation` once per parent.
    parent: str | None = None
    # How far back the API keeps rows. Fan-out endpoints send this window on every request.
    retention_seconds: int | None = None
    refresh_seconds: int = 0
    # The table to probe when validating, for endpoints that need a parent before they can be called.
    probe: str | None = None
    permissions: tuple[str, ...] = ()

    @property
    def is_events(self) -> bool:
        return self.operation == "LookupEvents"


AWS_CLOUDTRAIL_ENDPOINTS: dict[str, CloudTrailEndpoint] = {
    "events": CloudTrailEndpoint(
        operation="LookupEvents",
        result_key="Events",
        primary_key=("region", "event_id"),
        page_size=50,
        timestamps=("event_time",),
        incremental_field="event_time",
        partition_key="event_time",
    ),
    "insight_events": CloudTrailEndpoint(
        operation="LookupEvents",
        result_key="Events",
        primary_key=("region", "event_id"),
        page_size=50,
        event_category="insight",
        timestamps=("event_time",),
        incremental_field="event_time",
        partition_key="event_time",
    ),
    "trails": CloudTrailEndpoint(
        operation="DescribeTrails",
        result_key="trailList",
        primary_key=("trail_arn",),
    ),
    "event_data_stores": CloudTrailEndpoint(
        operation="ListEventDataStores",
        result_key="EventDataStores",
        primary_key=("event_data_store_arn",),
        page_size=100,
        timestamps=("created_timestamp", "updated_timestamp"),
    ),
    "insights_data": CloudTrailEndpoint(
        operation="ListInsightsData",
        result_key="Events",
        primary_key=("region", "trail_arn", "event_id"),
        page_size=50,
        timestamps=("event_time",),
        incremental_field="event_time",
        partition_key="event_time",
        parent="trails",
        retention_seconds=LOOKBACK_SECONDS,
        probe="trails",
        permissions=("DescribeTrails", "ListInsightsData"),
    ),
    "insights_metric_data": CloudTrailEndpoint(
        operation="ListInsightsMetricData",
        result_key="Values",
        primary_key=("region", "trail_arn", "event_source", "event_name", "insight_type", "error_code", "timestamp"),
        page_size=21600,
        partition_key="timestamp",
        parent="insight_series",
        probe="insight_events",
        permissions=("LookupEvents", "DescribeTrails", "ListInsightsData"),
    ),
    "lake_queries": CloudTrailEndpoint(
        operation="ListQueries",
        result_key="Queries",
        primary_key=("event_data_store_arn", "query_id"),
        page_size=1000,
        timestamps=("creation_time",),
        incremental_field="creation_time",
        partition_key="creation_time",
        parent="event_data_stores",
        retention_seconds=LAKE_QUERY_HISTORY_SECONDS,
        refresh_seconds=LAKE_QUERY_REFRESH_SECONDS,
        probe="event_data_stores",
        permissions=("ListEventDataStores", "ListQueries", "DescribeQuery"),
    ),
}
ENDPOINTS = tuple(AWS_CLOUDTRAIL_ENDPOINTS)
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(endpoint.incremental_field)]
    for name, endpoint in AWS_CLOUDTRAIL_ENDPOINTS.items()
    if endpoint.incremental_field is not None
}
ENDPOINT_DESCRIPTIONS = {
    "events": "Management events from the past 90 days in the selected AWS region. Data events are excluded.",
    "insight_events": "Insights events from the past 90 days for trails with Insights enabled in the selected region.",
    "trails": "Trail settings in the selected region, including shadow trails.",
    "event_data_stores": "CloudTrail Lake event store settings in the selected region. Stored events are excluded.",
    "insights_data": "Insights events from the past 90 days for trails with Insights enabled on data events.",
    "insights_metric_data": "Hourly API call and error rates from the past 90 days for each activity that triggered an Insights event.",
    "lake_queries": "CloudTrail Lake queries from the past 7 days, with their status, run time, and data scanned.",
}

ACCESS_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException"})
THROTTLE_CODES = frozenset({"Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"})
# A parent that cannot serve the child call (an organization trail seen from a member account, a trail
# without data event Insights, a stopped event store) is skipped rather than failing the whole table.
SKIPPED_PARENT_CODES = frozenset(
    {
        "InvalidParameterException",
        "OperationNotPermittedException",
        "UnsupportedOperationException",
        "TrailNotFoundException",
        "InvalidTrailNameException",
        "EventDataStoreNotFoundException",
        "InactiveEventDataStoreException",
    }
)
CREDENTIAL_ERRORS = {
    "UnrecognizedClientException": "AWS rejected the access key. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key. Check the access key ID and secret access key.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and selected region.",
    "ExpiredTokenException": "The AWS session token has expired. Reconnect with new credentials.",
    "ExpiredToken": "The AWS session token has expired. Reconnect with new credentials.",
    "SubscriptionRequiredException": "This AWS account needs access to the requested CloudTrail service. Check its service subscription.",
    "OptInRequired": "This AWS account needs access to the requested service or region. Enable access in AWS.",
    "OperationNotPermittedException": "AWS does not permit this operation. Check the account permissions and service availability.",
    "UnsupportedOperationException": "AWS does not support this operation in the selected region. Select a supported region.",
}
