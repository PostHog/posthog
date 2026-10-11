from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

CLOUDTRAIL_API_VERSION = "2013-11-01"
TARGET_PREFIXES = {CLOUDTRAIL_API_VERSION: "com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101"}
LOOKBACK_SECONDS = 90 * 24 * 60 * 60


@frozen
class CloudTrailEndpoint:
    operation: str
    result_key: str
    primary_key: tuple[str, ...]
    page_size: int | None = None
    event_category: str | None = None
    timestamps: tuple[str, ...] = ()

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
    ),
    "insight_events": CloudTrailEndpoint(
        operation="LookupEvents",
        result_key="Events",
        primary_key=("region", "event_id"),
        page_size=50,
        event_category="insight",
        timestamps=("event_time",),
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
}
ENDPOINTS = tuple(AWS_CLOUDTRAIL_ENDPOINTS)
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("event_time")] for name, endpoint in AWS_CLOUDTRAIL_ENDPOINTS.items() if endpoint.is_events
}
ENDPOINT_DESCRIPTIONS = {
    "events": "Management events from the past 90 days in the selected AWS region. Data events are excluded.",
    "insight_events": "Insights events from the past 90 days for trails with Insights enabled in the selected region.",
    "trails": "Trail settings in the selected region, including shadow trails.",
    "event_data_stores": "CloudTrail Lake event store settings in the selected region. Stored events are excluded.",
}

ACCESS_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException"})
THROTTLE_CODES = frozenset({"Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"})
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
