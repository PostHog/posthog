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


AWS_CONFIG_ENDPOINTS: dict[str, AwsConfigEndpoint] = {
    "resources": AwsConfigEndpoint(
        operation="SelectResourceConfig",
        result_key="Results",
        primary_key=("account_id", "aws_region", "resource_type", "resource_id"),
        description="Current configurations of recorded resources in the selected region. Excludes deleted resources.",
        page_size=100,
        expression=RESOURCE_EXPRESSION,
    ),
    "config_rules": AwsConfigEndpoint(
        operation="DescribeConfigRules",
        result_key="ConfigRules",
        primary_key=("config_rule_arn",),
        description="AWS Config rules, their evaluation settings, and resource scopes.",
    ),
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
