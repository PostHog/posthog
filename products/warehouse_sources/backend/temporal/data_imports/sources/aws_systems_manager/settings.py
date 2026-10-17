from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

API_VERSION = "2014-11-06"
API_DOCS_URL = "https://docs.aws.amazon.com/systems-manager/latest/APIReference/Welcome.html"


@frozen
class SystemsManagerEndpoint:
    operation: str
    result_key: str
    primary_key: tuple[str, ...]
    description: str
    page_size: int = 50
    probe_size: int = 1
    timestamps: tuple[str, ...] = ()


ENDPOINTS: dict[str, SystemsManagerEndpoint] = {
    "managed_instances": SystemsManagerEndpoint(
        operation="DescribeInstanceInformation",
        result_key="InstanceInformationList",
        primary_key=("region", "instance_id"),
        description="Managed nodes with agent, platform, and connection details. Stopped and terminated nodes are excluded.",
        probe_size=5,
        timestamps=(
            "last_ping_date_time",
            "registration_date",
            "last_association_execution_date",
            "last_successful_association_execution_date",
        ),
    ),
    "inventory": SystemsManagerEndpoint(
        operation="GetInventory",
        result_key="Entities",
        primary_key=("region", "id"),
        description="Collected AWS:InstanceInformation inventory, including stopped and terminated nodes.",
    ),
    "resource_compliance_summaries": SystemsManagerEndpoint(
        operation="ListResourceComplianceSummaries",
        result_key="ResourceComplianceSummaryItems",
        primary_key=("region", "resource_type", "resource_id", "compliance_type"),
        description="Compliance status and severity counts for each resource and compliance type.",
        timestamps=("execution_summary_execution_time",),
    ),
    "associations": SystemsManagerEndpoint(
        operation="ListAssociations",
        result_key="Associations",
        primary_key=("region", "association_id"),
        description="State Manager associations with schedules, targets, and execution status.",
        timestamps=("last_execution_date",),
    ),
    "patch_baselines": SystemsManagerEndpoint(
        operation="DescribePatchBaselines",
        result_key="BaselineIdentities",
        primary_key=("region", "baseline_id"),
        description="Patch baseline identities, operating systems, and default baseline flags.",
        page_size=100,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the ssm read permission for the selected table.",
    "AccessDeniedException": "AWS denied access. Grant the ssm read permission for the selected table.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key and secret, and include the token for temporary credentials.",
    "InvalidClientTokenId": "AWS rejected the access key. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and region.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and region.",
    "ExpiredToken": "The AWS session token expired. Enter new temporary credentials.",
    "ExpiredTokenException": "The AWS session token expired. Enter new temporary credentials.",
    "SubscriptionRequiredException": "Enable AWS Systems Manager for this account and region, then try again.",
    "OptInRequired": "Enable AWS Systems Manager for this account and region, then try again.",
}
