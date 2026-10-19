from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

CONFIG_API_VERSION = "2014-11-12"
TARGET_PREFIXES = {CONFIG_API_VERSION: "StarlingDoveService"}

RESOURCE_EXPRESSION = (
    "SELECT accountId, awsRegion, arn, resourceId, resourceType, resourceName, "
    "configuration, configurationItemCaptureTime, resourceCreationTime, tags"
)


@frozen
class AwsConfigEndpoint:
    operation: str
    result_key: str
    primary_key: tuple[str, ...]
    description: str
    page_size: int | None = None
    expression: str | None = None
    params: Mapping[str, Any] | None = None
    flatten: tuple[str, ...] = ()
    # Child endpoints run once per parent row, passing the parent's `parent_param` value through.
    parent: "AwsConfigEndpoint | None" = None
    parent_param: str | None = None


CONFIG_RULES = AwsConfigEndpoint(
    operation="DescribeConfigRules",
    result_key="ConfigRules",
    primary_key=("config_rule_arn",),
    description="AWS Config rules, their evaluation settings, and resource scopes.",
)

CONFIGURATION_AGGREGATORS = AwsConfigEndpoint(
    operation="DescribeConfigurationAggregators",
    result_key="ConfigurationAggregators",
    primary_key=("configuration_aggregator_arn",),
    description="Configuration aggregators in the selected region.",
    page_size=100,
)


AWS_CONFIG_ENDPOINTS: dict[str, AwsConfigEndpoint] = {
    "resources": AwsConfigEndpoint(
        operation="SelectResourceConfig",
        result_key="Results",
        primary_key=("account_id", "aws_region", "resource_type", "resource_id"),
        description="Current configurations of recorded resources in the selected region. Excludes deleted resources.",
        page_size=100,
        expression=RESOURCE_EXPRESSION,
    ),
    "config_rules": CONFIG_RULES,
    "rule_compliance": AwsConfigEndpoint(
        operation="DescribeComplianceByConfigRule",
        result_key="ComplianceByConfigRules",
        primary_key=("region", "config_rule_name"),
        description="Current compliance status and counts of noncompliant resources for each rule.",
    ),
    "conformance_packs": AwsConfigEndpoint(
        operation="DescribeConformancePacks",
        result_key="ConformancePackDetails",
        primary_key=("conformance_pack_arn",),
        description="Conformance packs and their deployment settings in the selected region.",
        page_size=20,
    ),
    "conformance_pack_compliance_scores": AwsConfigEndpoint(
        operation="ListConformancePackComplianceScores",
        result_key="ConformancePackComplianceScores",
        primary_key=("region", "conformance_pack_name"),
        description="Percentage of compliant rule and resource combinations in each conformance pack.",
        page_size=20,
    ),
    "rule_evaluation_results": AwsConfigEndpoint(
        operation="GetComplianceDetailsByConfigRule",
        result_key="EvaluationResults",
        primary_key=("region", "config_rule_name", "resource_type", "resource_id"),
        description="Latest evaluation result for each resource that each AWS Config rule evaluated.",
        page_size=100,
        # INSUFFICIENT_DATA is not a valid filter value, so the three filterable outcomes are listed explicitly.
        params={"ComplianceTypes": ["COMPLIANT", "NON_COMPLIANT", "NOT_APPLICABLE"]},
        flatten=("EvaluationResultIdentifier", "EvaluationResultQualifier"),
        parent=CONFIG_RULES,
        parent_param="ConfigRuleName",
    ),
    "aggregated_resources": AwsConfigEndpoint(
        operation="SelectAggregateResourceConfig",
        result_key="Results",
        primary_key=("configuration_aggregator_name", "account_id", "aws_region", "resource_type", "resource_id"),
        description="Current configurations of resources across the accounts and regions of each configuration aggregator in the selected region.",
        page_size=100,
        expression=RESOURCE_EXPRESSION,
        parent=CONFIGURATION_AGGREGATORS,
        parent_param="ConfigurationAggregatorName",
    ),
}

ENDPOINTS = tuple(AWS_CONFIG_ENDPOINTS)
ENDPOINT_DESCRIPTIONS = {name: endpoint.description for name, endpoint in AWS_CONFIG_ENDPOINTS.items()}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the config read permission for the selected table to this IAM user or role.",
    "AccessDeniedException": "AWS denied access. Grant the config read permission for the selected table to this IAM user or role.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and session token.",
    "ExpiredTokenException": "The AWS session token has expired. Enter new temporary credentials.",
    "ExpiredToken": "The AWS session token has expired. Enter new temporary credentials.",
    "MissingAuthenticationToken": "AWS did not receive valid credentials. Enter the access key ID and secret access key.",
    "OptInRequired": "Enable AWS Config in the selected account and region, then try again.",
    "SubscriptionRequiredException": "Enable AWS Config in the selected account and region, then try again.",
    "NoAvailableConfigurationRecorderException": "Set up an AWS Config recorder in the selected region, then try again.",
}
