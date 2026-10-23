from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

GUARDDUTY_API_VERSION = "2017-11-28"
MAX_RESULTS = 50


@frozen
class GuarddutyEndpoint:
    operation: str
    result_key: str | None
    primary_keys: tuple[str, ...]
    iam_actions: tuple[str, ...]
    partition_key: str | None = None


ENDPOINTS = {
    "findings": GuarddutyEndpoint(
        operation="ListFindings",
        result_key="findingIds",
        primary_keys=("arn",),
        iam_actions=("guardduty:ListDetectors", "guardduty:ListFindings", "guardduty:GetFindings"),
        partition_key="created_at",
    ),
    "detectors": GuarddutyEndpoint(
        operation="GetDetector",
        result_key=None,
        primary_keys=("region", "source_detector_id"),
        iam_actions=("guardduty:ListDetectors", "guardduty:GetDetector"),
    ),
    "members": GuarddutyEndpoint(
        operation="ListMembers",
        result_key="members",
        primary_keys=("region", "source_detector_id", "account_id"),
        iam_actions=("guardduty:ListDetectors", "guardduty:ListMembers"),
    ),
    "coverage": GuarddutyEndpoint(
        operation="ListCoverage",
        result_key="resources",
        primary_keys=("region", "source_detector_id", "account_id", "resource_id"),
        iam_actions=("guardduty:ListDetectors", "guardduty:ListCoverage"),
    ),
    "malware_scans": GuarddutyEndpoint(
        operation="DescribeMalwareScans",
        result_key="scans",
        primary_keys=("region", "source_detector_id", "scan_id"),
        iam_actions=("guardduty:ListDetectors", "guardduty:DescribeMalwareScans"),
        partition_key="scan_start_time",
    ),
    "usage_statistics": GuarddutyEndpoint(
        operation="GetUsageStatistics",
        result_key="usageStatistics",
        primary_keys=("region", "source_detector_id", "usage_statistic_type", "usage_key"),
        iam_actions=("guardduty:ListDetectors", "guardduty:GetUsageStatistics"),
    ),
}

# Statistic type -> (response list key, row field that identifies the usage line).
USAGE_STATISTIC_TYPES = {
    "SUM_BY_ACCOUNT": ("sumByAccount", "accountId"),
    "SUM_BY_FEATURES": ("sumByFeature", "feature"),
    "SUM_BY_RESOURCE": ("sumByResource", "resource"),
}
# The API sums only the features named in the request, so list every feature it reports usage for.
USAGE_FEATURES = (
    "FLOW_LOGS",
    "CLOUD_TRAIL",
    "DNS_LOGS",
    "S3_DATA_EVENTS",
    "EKS_AUDIT_LOGS",
    "EBS_MALWARE_PROTECTION",
    "RDS_LOGIN_EVENTS",
    "LAMBDA_NETWORK_LOGS",
    "EKS_RUNTIME_MONITORING",
    "EC2_RUNTIME_MONITORING",
    "FARGATE_RUNTIME_MONITORING",
    "RDS_DBI_PROTECTION_PROVISIONED",
    "RDS_DBI_PROTECTION_SERVERLESS",
    "RDS_DBI_PROTECTION_LIMITLESS",
    "RDS_DATA_ACTIVITY_DBI_PROTECTION_PROVISIONED",
    "RDS_DATA_ACTIVITY_DBI_PROTECTION_SERVERLESS",
    "RDS_DATA_ACTIVITY_DBI_PROTECTION_LIMITLESS",
    "AI_PROTECTION",
)

INCREMENTAL_FIELDS = {"findings": [incremental_field("updated_at")]}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Threat findings, including severity, affected resources, and detection details.",
    "detectors": "Detector status, enabled features, and configuration in the selected region.",
    "members": "Member accounts and their relationship with the GuardDuty administrator account.",
    "coverage": "Runtime Monitoring coverage status for EKS clusters, ECS clusters, and EC2 instances.",
    "malware_scans": "Malware Protection for EC2 scans, including status, result, trigger, and scanned data volume.",
    "usage_statistics": "GuardDuty usage cost over the last 30 days, summed by account, feature, and resource.",
}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the GuardDuty read permissions listed in the source setup.",
    "ForbiddenException": "AWS denied access. Grant the GuardDuty read permissions listed in the source setup.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "ExpiredToken": "The AWS session token expired. Reconnect with current credentials.",
    "SubscriptionRequiredException": "Enable GuardDuty in the selected AWS region, then reconnect.",
}
