from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "resources": {
        "description": "Current configurations of recorded AWS resources in the selected region. Excludes deleted resources.",
        "docs_url": "https://docs.aws.amazon.com/config/latest/APIReference/API_SelectResourceConfig.html",
        "columns": {
            "account_id": "AWS account that owns the resource.",
            "aws_region": "AWS region reported for the resource.",
            "region": "AWS region selected for this import.",
            "arn": "Amazon Resource Name of the resource.",
            "resource_id": "Resource identifier assigned by its AWS service.",
            "resource_type": "AWS resource type, such as AWS::EC2::Instance.",
            "resource_name": "Resource name, when the service provides one.",
            "configuration": "Configuration properties recorded for the resource.",
            "configuration_item_capture_time": "Time when AWS Config recorded this configuration.",
            "resource_creation_time": "Time when the resource was created, when available.",
            "tags": "Tags attached to the resource.",
        },
    },
    "config_rules": {
        "description": "AWS Config rules and their evaluation settings in the selected region.",
        "docs_url": "https://docs.aws.amazon.com/config/latest/APIReference/API_DescribeConfigRules.html",
        "columns": {
            "config_rule_arn": "Amazon Resource Name of the rule.",
            "config_rule_id": "Identifier assigned to the rule by AWS Config.",
            "config_rule_name": "Name of the AWS Config rule.",
            "config_rule_state": "Current state of the rule.",
            "description": "Description of the rule.",
            "scope": "Resource types, identifiers, or tags that restrict the rule's evaluations.",
            "source": "Rule owner, identifier, and evaluation triggers.",
            "input_parameters": "Parameters passed to the rule as a JSON string.",
            "maximum_execution_frequency": "Maximum frequency for periodic evaluations.",
            "region": "AWS region selected for this import.",
        },
    },
    "rule_compliance": {
        "description": "Current compliance status for AWS Config rules, including counts of noncompliant resources.",
        "docs_url": "https://docs.aws.amazon.com/config/latest/APIReference/API_DescribeComplianceByConfigRule.html",
        "columns": {
            "config_rule_name": "Name of the evaluated AWS Config rule.",
            "compliance": "Compliance status and a capped count of contributing resources, with an indicator when the cap is exceeded.",
            "region": "AWS region selected for this import.",
        },
    },
    "conformance_packs": {
        "description": "Conformance packs and their deployment settings in the selected region.",
        "docs_url": "https://docs.aws.amazon.com/config/latest/APIReference/API_DescribeConformancePacks.html",
        "columns": {
            "conformance_pack_arn": "Amazon Resource Name of the conformance pack.",
            "conformance_pack_id": "Identifier assigned to the conformance pack.",
            "conformance_pack_name": "Name of the conformance pack.",
            "conformance_pack_input_parameters": "Parameters used to deploy the conformance pack.",
            "delivery_s3_bucket": "S3 bucket used for the conformance pack template.",
            "delivery_s3_key_prefix": "S3 prefix used for the conformance pack template.",
            "last_update_requested_time": "Time when the most recent update was requested.",
            "created_by": "AWS service that created the conformance pack.",
            "region": "AWS region selected for this import.",
        },
    },
}
