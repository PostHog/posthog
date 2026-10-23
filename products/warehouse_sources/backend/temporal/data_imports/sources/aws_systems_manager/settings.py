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
    # Endpoint whose rows supply the required identifiers for each request to this one.
    parent: str | None = None


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
    "documents": SystemsManagerEndpoint(
        operation="ListDocuments",
        result_key="DocumentIdentifiers",
        primary_key=("region", "owner", "name"),
        description="SSM documents owned by you, shared with you, or provided by AWS, with types, versions, and platforms.",
        timestamps=("created_date",),
    ),
    "compliance_items": SystemsManagerEndpoint(
        operation="ListComplianceItems",
        result_key="ComplianceItems",
        primary_key=("region", "resource_type", "resource_id", "compliance_type", "id"),
        description="Individual patch, association, and custom compliance results behind each resource compliance summary.",
        timestamps=("execution_summary_execution_time",),
        parent="resource_compliance_summaries",
    ),
    "inventory_entries": SystemsManagerEndpoint(
        operation="ListInventoryEntries",
        result_key="Entries",
        primary_key=("region", "instance_id", "type_name", "entry_id"),
        description="Inventory entries of every collected type except AWS:InstanceInformation, such as applications and services, for each node.",
        parent="inventory",
    ),
    "association_executions": SystemsManagerEndpoint(
        operation="DescribeAssociationExecutions",
        result_key="AssociationExecutions",
        primary_key=("region", "association_id", "execution_id"),
        description="Execution history of each State Manager association, with status and resource counts by status.",
        timestamps=("created_time", "last_execution_date"),
        parent="associations",
    ),
    "association_execution_targets": SystemsManagerEndpoint(
        operation="DescribeAssociationExecutionTargets",
        result_key="AssociationExecutionTargets",
        primary_key=("region", "association_id", "execution_id", "resource_type", "resource_id"),
        description="Status of each resource targeted by an association execution.",
        timestamps=("last_execution_date",),
        parent="association_executions",
    ),
    "instance_patch_states": SystemsManagerEndpoint(
        operation="DescribeInstancePatchStates",
        result_key="InstancePatchStates",
        primary_key=("region", "instance_id"),
        description="Patch counts by state, the patch baseline, and the last patch operation for each managed node.",
        probe_size=10,
        timestamps=("operation_start_time", "operation_end_time", "last_no_reboot_install_operation_time"),
        parent="managed_instances",
    ),
    "instance_patches": SystemsManagerEndpoint(
        operation="DescribeInstancePatches",
        result_key="Patches",
        primary_key=("region", "instance_id", "kb_id", "title"),
        description="Installed, missing, and failed patches on each managed node, with classification and severity.",
        page_size=100,
        probe_size=10,
        timestamps=("installed_time",),
        parent="managed_instances",
    ),
    "sessions": SystemsManagerEndpoint(
        operation="DescribeSessions",
        result_key="Sessions",
        primary_key=("region", "session_id"),
        description="Active Session Manager sessions and sessions that ended in the past 30 days.",
        page_size=200,
        timestamps=("start_date", "end_date"),
    ),
    "ops_items": SystemsManagerEndpoint(
        operation="DescribeOpsItems",
        result_key="OpsItemSummaries",
        primary_key=("region", "ops_item_id"),
        description="OpsCenter OpsItems with status, priority, severity, and planned and actual times.",
        timestamps=(
            "created_time",
            "last_modified_time",
            "actual_start_time",
            "actual_end_time",
            "planned_start_time",
            "planned_end_time",
        ),
    ),
    "ops_item_events": SystemsManagerEndpoint(
        operation="ListOpsItemEvents",
        result_key="Summaries",
        primary_key=("region", "ops_item_id", "event_id"),
        description="Events that changed OpsItems, with the event source, detail, and creation time.",
        timestamps=("created_time",),
    ),
}

# Ended sessions first, so a session that ends between the two requests cannot appear twice under one key.
SESSION_STATES = ("History", "Active")

# Other tables already sync these inventory types.
EXCLUDED_INVENTORY_TYPES = frozenset({"AWS:InstanceInformation", "AWS:ComplianceItem", "AWS:ComplianceSummary"})

# A parent can disappear between listing it and reading its children.
MISSING_PARENT_ERRORS = frozenset(
    {"AssociationDoesNotExist", "AssociationExecutionDoesNotExist", "InvalidInstanceId", "InvalidResourceId"}
)

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
