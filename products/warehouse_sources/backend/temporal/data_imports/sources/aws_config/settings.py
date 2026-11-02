import datetime as dt
from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

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
    limit_key: str = "Limit"
    token_key: str = "NextToken"
    # Child endpoints run once per parent row, passing the parent's `parent_params` values through.
    parent: "AwsConfigEndpoint | None" = None
    parent_params: tuple[str, ...] = ()
    # Error codes that mean one parent has nothing to read, such as a rule without remediation.
    empty_error_codes: frozenset[str] = frozenset()
    incremental_field: str | None = None
    # Request path that takes the incremental start time, in epoch seconds.
    incremental_filter: tuple[str, ...] = ()
    # Start time for a read without an incremental value. None reads everything the API keeps.
    initial_window: dt.timedelta | None = None
    partition_key: str | None = None


CONFIG_RULES = AwsConfigEndpoint(
    operation="DescribeConfigRules",
    result_key="ConfigRules",
    primary_key=("config_rule_arn",),
    description="AWS Config rules, their evaluation settings, and resource scopes.",
)

CONFORMANCE_PACKS = AwsConfigEndpoint(
    operation="DescribeConformancePacks",
    result_key="ConformancePackDetails",
    primary_key=("conformance_pack_arn",),
    description="Conformance packs and their deployment settings in the selected region.",
    page_size=20,
)

RESOURCE_KEYS = AwsConfigEndpoint(
    operation="SelectResourceConfig",
    result_key="Results",
    primary_key=("resource_type", "resource_id"),
    description="Type and identifier of each recorded resource.",
    page_size=100,
    expression="SELECT resourceType, resourceId",
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
    "conformance_packs": CONFORMANCE_PACKS,
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
        parent_params=("ConfigRuleName",),
    ),
    "aggregated_resources": AwsConfigEndpoint(
        operation="SelectAggregateResourceConfig",
        result_key="Results",
        primary_key=("configuration_aggregator_name", "account_id", "aws_region", "resource_type", "resource_id"),
        description="Current configurations of resources across the accounts and regions of each configuration aggregator in the selected region.",
        page_size=100,
        expression=RESOURCE_EXPRESSION,
        parent=CONFIGURATION_AGGREGATORS,
        parent_params=("ConfigurationAggregatorName",),
    ),
    "resource_config_history": AwsConfigEndpoint(
        operation="GetResourceConfigHistory",
        result_key="configurationItems",
        primary_key=("account_id", "aws_region", "resource_type", "resource_id", "configuration_state_id"),
        description=(
            "Configuration items recorded for each current resource in the selected region. "
            "Without a saved incremental value, the table reads the last 90 days."
        ),
        page_size=100,
        limit_key="limit",
        token_key="nextToken",
        parent=RESOURCE_KEYS,
        parent_params=("resourceType", "resourceId"),
        empty_error_codes=frozenset({"ResourceNotDiscoveredException"}),
        incremental_field="configuration_item_capture_time",
        incremental_filter=("earlierTime",),
        # One history call covers at most seven days, so reading years of history for each resource is too slow.
        initial_window=dt.timedelta(days=90),
        partition_key="configuration_item_capture_time",
    ),
    "conformance_pack_evaluation_results": AwsConfigEndpoint(
        operation="GetConformancePackComplianceDetails",
        result_key="ConformancePackRuleEvaluationResults",
        primary_key=("region", "conformance_pack_name", "config_rule_name", "resource_type", "resource_id"),
        description="Latest evaluation result for each rule and resource in each conformance pack.",
        page_size=100,
        flatten=("EvaluationResultIdentifier", "EvaluationResultQualifier"),
        parent=CONFORMANCE_PACKS,
        parent_params=("ConformancePackName",),
        empty_error_codes=frozenset({"NoSuchConformancePackException"}),
    ),
    "remediation_execution_statuses": AwsConfigEndpoint(
        operation="DescribeRemediationExecutionStatus",
        result_key="RemediationExecutionStatuses",
        primary_key=("region", "config_rule_name", "resource_type", "resource_id"),
        description="State and step details of the latest remediation execution for each resource and rule.",
        page_size=100,
        flatten=("ResourceKey",),
        parent=CONFIG_RULES,
        parent_params=("ConfigRuleName",),
        empty_error_codes=frozenset({"NoSuchRemediationConfigurationException"}),
    ),
    "resource_evaluations": AwsConfigEndpoint(
        operation="ListResourceEvaluations",
        result_key="ResourceEvaluations",
        primary_key=("resource_evaluation_id",),
        description="Proactive evaluations of resource configurations, usually run before deployment.",
        page_size=100,
        incremental_field="evaluation_start_timestamp",
        incremental_filter=("Filters", "TimeWindow", "StartTime"),
        partition_key="evaluation_start_timestamp",
    ),
}

ENDPOINTS = tuple(AWS_CONFIG_ENDPOINTS)
ENDPOINT_DESCRIPTIONS = {name: endpoint.description for name, endpoint in AWS_CONFIG_ENDPOINTS.items()}
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(endpoint.incremental_field)]
    for name, endpoint in AWS_CONFIG_ENDPOINTS.items()
    if endpoint.incremental_field is not None
}
# A configuration item can reach the API after its capture time, so each sync reads the last hour again.
INCREMENTAL_LOOKBACK_SECONDS = {"resource_config_history": 3600}

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
