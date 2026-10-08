from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

INSPECTOR_API_VERSION = "2020-06-08"
DEFAULT_REGION = "us-east-1"


@frozen
class AwsInspectorEndpoint:
    operation: str
    path: str
    result_key: str
    primary_keys: tuple[str, ...]
    page_size: int | None = None
    timestamp_columns: tuple[str, ...] = ()
    partition_key: str | None = None


AWS_INSPECTOR_ENDPOINTS = {
    "findings": AwsInspectorEndpoint(
        operation="ListFindings",
        path="/findings/list",
        result_key="findings",
        primary_keys=("finding_arn",),
        page_size=25,
        timestamp_columns=("first_observed_at", "last_observed_at", "updated_at"),
        partition_key="first_observed_at",
    ),
    "coverage": AwsInspectorEndpoint(
        operation="ListCoverage",
        path="/coverage/list",
        result_key="coveredResources",
        primary_keys=("region", "account_id", "resource_type", "resource_id", "scan_type"),
        page_size=200,
        timestamp_columns=("last_scanned_at",),
    ),
    "coverage_statistics": AwsInspectorEndpoint(
        operation="ListCoverageStatistics",
        path="/coverage/statistics/list",
        result_key="countsByGroup",
        primary_keys=("region", "group_key"),
    ),
}
ENDPOINTS = tuple(AWS_INSPECTOR_ENDPOINTS)
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "findings": [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Vulnerability and network reachability findings for resources in the selected AWS region.",
    "coverage": "Resources and scan types monitored by Amazon Inspector in the selected AWS region.",
    "coverage_statistics": "Resource counts grouped by resource type in the selected AWS region.",
}

ERROR_MESSAGES = {
    "AccessDenied": "Grant inspector2:ListFindings, inspector2:ListCoverage, or inspector2:ListCoverageStatistics for the tables you select.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is correct and active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and session token.",
    "ExpiredToken": "The AWS session token expired. Connect again with new credentials.",
    "SubscriptionRequiredException": "Enable Amazon Inspector in the selected AWS region, then try again.",
    "OptInRequired": "Enable Amazon Inspector in the selected AWS region, then try again.",
    "HTTP 401": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "HTTP 403": "AWS denied access. Check the IAM permissions for the selected tables.",
}
