from typing import Any

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
    # None for operations that return everything in one response and take no MaxResults.
    page_size: int | None = 100
    params: tuple[tuple[str, Any], ...] = ()
    # Endpoint whose rows supply this endpoint's required path parameter, with that row field.
    parent: tuple[str, str] | None = None


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
    "standards_controls": SecurityHubEndpoint(
        operation="DescribeStandardsControls",
        result_key="Controls",
        primary_keys=("standards_subscription_arn", "standards_control_arn"),
        parent=("enabled_standards", "StandardsSubscriptionArn"),
    ),
    "security_control_definitions": SecurityHubEndpoint(
        operation="ListSecurityControlDefinitions",
        result_key="SecurityControlDefinitions",
        primary_keys=("security_control_id",),
    ),
    "products": SecurityHubEndpoint(operation="DescribeProducts", result_key="Products", primary_keys=("product_arn",)),
    "members": SecurityHubEndpoint(
        operation="ListMembers",
        result_key="Members",
        primary_keys=("account_id",),
        page_size=50,
        # The API defaults to enabled members only. Include invited and removed accounts too.
        params=(("OnlyAssociated", False),),
    ),
    "remediations": SecurityHubEndpoint(
        operation="GetRemediationsV2", result_key="Items", primary_keys=("target_uid",)
    ),
    "remediation_exposures": SecurityHubEndpoint(
        operation="ListExposuresByRemediationV2",
        result_key="Items",
        # One exposure finding can link to several remediation targets.
        primary_keys=("target_uid", "metadata_uid"),
        parent=("remediations", "TargetUid"),
    ),
    "insight_results": SecurityHubEndpoint(
        operation="GetInsightResults",
        result_key="InsightResults",
        primary_keys=("insight_arn", "group_by_attribute_value"),
        page_size=None,
        parent=("insights", "InsightArn"),
    ),
    # Fans out over every finding. Each request takes the finding's Id and ProductArn.
    "finding_history": SecurityHubEndpoint(
        operation="GetFindingHistory",
        result_key="Records",
        primary_keys=("product_arn", "finding_id", "update_time"),
        partition_key="update_time",
    ),
    "findings_v2": SecurityHubEndpoint(
        operation="GetFindingsV2", result_key="Findings", primary_keys=("product_uid", "finding_uid")
    ),
    "resources_v2": SecurityHubEndpoint(
        operation="GetResourcesV2",
        result_key="Resources",
        primary_keys=("account_id", "region", "resource_type", "resource_id"),
    ),
}

# The pinned botocore model predates these operations. Each one is a POST with only JSON body members.
UNMODELED_OPERATION_PATHS = {
    "GetRemediationsV2": "/GetRemediationsV2",
    "ListExposuresByRemediationV2": "/ListExposuresByRemediationV2",
}

INCREMENTAL_FIELDS = {
    "findings": [incremental_field("updated_at")],
    "finding_history": [incremental_field("update_time")],
    "findings_v2": [incremental_field("modified_time")],
}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Security findings with severity, resources, compliance status, and workflow status.",
    "standards": "Available security standards and their descriptions.",
    "enabled_standards": "Enabled security standards and their subscription status.",
    "insights": "Custom insights with their filters and grouping fields. AWS managed insights are excluded.",
    "standards_controls": "Controls in each enabled standard, with enablement status, severity, and disablement reasons.",
    "security_control_definitions": "Security control definitions with titles, severity, and remediation guidance.",
    "products": "Product integrations that can send findings to Security Hub, with vendor names and descriptions.",
    "members": "Member accounts of the Security Hub administrator account and their relationship status.",
    "remediations": "Remediation targets for exposure findings, sorted by priority, with their expected outcome and affected resource.",
    "remediation_exposures": "Exposure findings linked to each remediation target, with severity before and after the fix.",
    "insight_results": "Finding counts for each group of every custom insight.",
    "finding_history": "Changes to each finding over time, with the fields that changed and who changed them.",
    "findings_v2": "Security Hub findings in the Open Cybersecurity Schema Framework (OCSF) format.",
    "resources_v2": "Resources that Security Hub tracks, with their configuration, tags, and finding summaries.",
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
