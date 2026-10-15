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
    # A fan-out table probes and walks this listing, then calls its own operation once per listed item.
    parent: "AwsInspectorEndpoint | None" = None

    @property
    def iam_actions(self) -> tuple[str, ...]:
        parent_actions = self.parent.iam_actions if self.parent else ()
        return (*parent_actions, f"inspector2:{self.operation}")


COVERAGE_ENDPOINT = AwsInspectorEndpoint(
    operation="ListCoverage",
    path="/coverage/list",
    result_key="coveredResources",
    primary_keys=("region", "account_id", "resource_type", "resource_id", "scan_type"),
    page_size=200,
    timestamp_columns=("last_scanned_at",),
)
CIS_SCANS_ENDPOINT = AwsInspectorEndpoint(
    operation="ListCisScans",
    path="/cis/scan/list",
    result_key="scans",
    primary_keys=("scan_arn",),
    page_size=100,
    timestamp_columns=("scan_date",),
    partition_key="scan_date",
)
CIS_SCAN_TARGETS_ENDPOINT = AwsInspectorEndpoint(
    operation="ListCisScanResultsAggregatedByTargetResource",
    path="/cis/scan-result/resource/list",
    result_key="targetResourceAggregations",
    primary_keys=("scan_arn", "account_id", "target_resource_id"),
    page_size=100,
    parent=CIS_SCANS_ENDPOINT,
)


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
    "coverage": COVERAGE_ENDPOINT,
    "coverage_statistics": AwsInspectorEndpoint(
        operation="ListCoverageStatistics",
        path="/coverage/statistics/list",
        result_key="countsByGroup",
        primary_keys=("region", "group_key"),
    ),
    "members": AwsInspectorEndpoint(
        operation="ListMembers",
        path="/members/list",
        result_key="members",
        primary_keys=("region", "account_id"),
        page_size=50,
        timestamp_columns=("updated_at",),
    ),
    "cis_scans": CIS_SCANS_ENDPOINT,
    "cis_scan_result_details": AwsInspectorEndpoint(
        operation="GetCisScanResultDetails",
        path="/cis/scan-result/details/get",
        result_key="scanResultDetails",
        primary_keys=("scan_arn", "account_id", "target_resource_id", "check_id"),
        page_size=1000,
        timestamp_columns=("scan_date",),
        partition_key="scan_date",
        parent=CIS_SCAN_TARGETS_ENDPOINT,
    ),
    "clusters_for_image": AwsInspectorEndpoint(
        operation="GetClustersForImage",
        path="/cluster/get",
        result_key="cluster",
        primary_keys=("resource_id", "cluster_arn"),
        page_size=100,
        parent=COVERAGE_ENDPOINT,
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
    ],
    "cis_scan_result_details": [
        {
            "label": "scan_date",
            "type": IncrementalFieldType.DateTime,
            "field": "scan_date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Vulnerability and network reachability findings for resources in the selected AWS region.",
    "coverage": "Resources and scan types monitored by Amazon Inspector in the selected AWS region.",
    "coverage_statistics": "Resource counts grouped by resource type in the selected AWS region.",
    "members": "Member accounts of the Amazon Inspector delegated administrator, with their relationship status.",
    "cis_scans": "CIS benchmark scans with their status and passed and failed check counts.",
    "cis_scan_result_details": "Outcome of each CIS benchmark check for each scanned resource.",
    "clusters_for_image": "Amazon ECS and Amazon EKS clusters that run each Amazon ECR image Inspector covers.",
}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the Amazon Inspector IAM permissions listed in the source setup for the tables you select.",
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
