from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "managed_instances": {
        "description": "Managed nodes in the selected region. Stopped and terminated nodes are excluded.",
        "docs_url": "https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_DescribeInstanceInformation.html",
        "columns": {
            "region": "AWS region selected for this source.",
            "instance_id": "Identifier of the managed node.",
            "agent_version": "Version of SSM Agent installed on the node.",
            "ping_status": "Connection status reported by SSM Agent.",
            "last_ping_date_time": "Time when SSM Agent last contacted Systems Manager.",
            "platform_type": "Operating system family of the managed node.",
            "platform_name": "Operating system name reported by the node.",
            "platform_version": "Operating system version reported by the node.",
            "ip_address": "IP address of the managed node.",
            "registration_date": "Time when the node registered with Systems Manager.",
        },
    },
    "inventory": {
        "description": "Collected instance inventory, including stopped and terminated nodes.",
        "docs_url": "https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetInventory.html",
        "columns": {
            "region": "AWS region selected for this source.",
            "id": "Identifier of the managed node that owns this inventory.",
            "data": "JSON containing AWS:InstanceInformation content, capture time, and schema version.",
        },
    },
    "resource_compliance_summaries": {
        "description": "Compliance results grouped by resource and compliance type in the selected region.",
        "docs_url": "https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_ListResourceComplianceSummaries.html",
        "columns": {
            "region": "AWS region selected for this source.",
            "resource_id": "Identifier of the resource checked for compliance.",
            "resource_type": "Type of resource checked for compliance.",
            "compliance_type": "Compliance category, such as Patch or Association.",
            "status": "Overall compliance status of this resource for this category.",
            "overall_severity": "Highest severity of the compliance results.",
            "compliant_summary_compliant_count": "Number of compliant items.",
            "non_compliant_summary_non_compliant_count": "Number of items that are not compliant.",
            "execution_summary_execution_time": "Time of the execution that produced these compliance results.",
        },
    },
    "associations": {
        "description": "State Manager associations with their targets, schedules, and execution status.",
        "docs_url": "https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_ListAssociations.html",
        "columns": {
            "region": "AWS region selected for this source.",
            "association_id": "Identifier of the association.",
            "association_name": "Name assigned to the association.",
            "name": "Name of the SSM document used by the association.",
            "association_version": "Version of the association.",
            "document_version": "Version of the SSM document used by the association.",
            "last_execution_date": "Time when the association last ran.",
            "schedule_expression": "Schedule that controls when the association runs.",
            "targets": "Resources selected by the association.",
        },
    },
    "patch_baselines": {
        "description": "Patch baseline identities and supported operating systems in the selected region.",
        "docs_url": "https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_DescribePatchBaselines.html",
        "columns": {
            "region": "AWS region selected for this source.",
            "baseline_id": "Identifier of the patch baseline.",
            "baseline_name": "Name assigned to the patch baseline.",
            "baseline_description": "Description assigned to the patch baseline.",
            "default_baseline": "Whether this is the default baseline for its operating system.",
            "operating_system": "Operating system supported by the patch baseline.",
        },
    },
}
