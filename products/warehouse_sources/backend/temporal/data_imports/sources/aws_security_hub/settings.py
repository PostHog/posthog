from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

SECURITY_HUB_API_VERSION = "2018-10-26"
API_DOCS_URL = "https://docs.aws.amazon.com/securityhub/1.0/APIReference/"


@frozen
class SecurityHubEndpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    partition_key: str | None = None


ENDPOINTS: dict[str, SecurityHubEndpoint] = {
    "findings": SecurityHubEndpoint(
        operation="GetFindings",
        result_key="Findings",
        primary_keys=("product_arn", "aws_account_id", "region", "id"),
        partition_key="created_at",
    ),
    "standards": SecurityHubEndpoint(
        operation="DescribeStandards", result_key="Standards", primary_keys=("standards_arn",)
    ),
    "enabled_standards": SecurityHubEndpoint(
        operation="GetEnabledStandards",
        result_key="StandardsSubscriptions",
        primary_keys=("standards_subscription_arn",),
    ),
    "insights": SecurityHubEndpoint(operation="GetInsights", result_key="Insights", primary_keys=("insight_arn",)),
}

INCREMENTAL_FIELDS = {"findings": [incremental_field("updated_at")]}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Security findings with severity, resources, compliance status, and workflow status.",
    "standards": "Available security standards and their descriptions.",
    "enabled_standards": "Enabled security standards and their subscription status.",
    "insights": "Custom insights with their filters and grouping fields. AWS managed insights are excluded.",
}

ACCESS_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException", "InvalidAccessException"})
CREDENTIAL_ERROR_CODES = frozenset(
    {"UnrecognizedClientException", "InvalidClientTokenId", "InvalidSignatureException", "SignatureDoesNotMatch"}
)
SUBSCRIPTION_MESSAGE = "Enable AWS Security Hub CSPM in the configured region, then try again."
ERROR_MESSAGES = {
    **dict.fromkeys(
        CREDENTIAL_ERROR_CODES, "AWS rejected the credentials. Check the access key and secret access key."
    ),
    **dict.fromkeys(ACCESS_DENIED_CODES, "Grant the required securityhub read permissions to this IAM user or role."),
    "ExpiredToken": "The AWS session token expired. Reconnect with new credentials.",
    "ExpiredTokenException": "The AWS session token expired. Reconnect with new credentials.",
    "SubscriptionRequiredException": SUBSCRIPTION_MESSAGE,
}
