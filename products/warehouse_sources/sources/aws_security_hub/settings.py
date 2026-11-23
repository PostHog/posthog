from typing import Any

from products.warehouse_sources.sources.sdk import frozen, incremental_field

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
    # Trend operations need a StartTime and EndTime. AWS keeps trend data for one year and picks the granularity.
    trend_window_days: int | None = None
    # AWS rejects a NextToken one hour after it issues it, so a resume from an old checkpoint can fail.
    token_expires: bool = False


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
    # V2 products have no ARN, so the company and product names identify each one.
    "products_v2": SecurityHubEndpoint(
        operation="DescribeProductsV2", result_key="ProductsV2", primary_keys=("company_name", "product_v2_name")
    ),
    "software_v2": SecurityHubEndpoint(
        operation="GetSoftwareV2",
        result_key="Software",
        primary_keys=("package_type", "package_name", "package_version"),
        token_expires=True,
    ),
    "findings_trends_v2": SecurityHubEndpoint(
        operation="GetFindingsTrendsV2",
        result_key="TrendsMetrics",
        primary_keys=("granularity", "timestamp"),
        trend_window_days=90,
    ),
    "resources_trends_v2": SecurityHubEndpoint(
        operation="GetResourcesTrendsV2",
        result_key="TrendsMetrics",
        primary_keys=("granularity", "timestamp"),
        trend_window_days=90,
    ),
}

# The pinned botocore model predates these operations. Each one is a POST with only JSON body members.
UNMODELED_OPERATION_PATHS = {
    "GetRemediationsV2": "/GetRemediationsV2",
    "ListExposuresByRemediationV2": "/ListExposuresByRemediationV2",
    "GetSoftwareV2": "/softwarev2",
    "GetFindingsTrendsV2": "/findingsTrendsv2",
    "GetResourcesTrendsV2": "/resourcesTrendsv2",
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
    "products_v2": "Product integrations for Security Hub, with company names, categories, and integration types.",
    "software_v2": "Software packages installed on your resources, with the number of resources that have each package.",
    "findings_trends_v2": "Daily, weekly, or monthly finding counts by severity for the last 90 days.",
    "resources_trends_v2": "Daily, weekly, or monthly resource counts for the last 90 days.",
}

ACCESS_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException", "InvalidAccessException"})
CREDENTIAL_ERROR_CODES = frozenset(
    {"UnrecognizedClientException", "InvalidClientTokenId", "InvalidSignatureException", "SignatureDoesNotMatch"}
)
SUBSCRIPTION_MESSAGE = (
    "Enable AWS Security Hub CSPM in the configured region, then try again. "
    "The software, trend, and V2 product tables need AWS Security Hub in that region too."
)
ERROR_MESSAGES = {
    **dict.fromkeys(
        CREDENTIAL_ERROR_CODES, "AWS rejected the credentials. Check the access key and secret access key."
    ),
    **dict.fromkeys(ACCESS_DENIED_CODES, "Grant the required securityhub read permissions to this IAM user or role."),
    "ExpiredToken": "The AWS session token expired. Reconnect with new credentials.",
    "ExpiredTokenException": "The AWS session token expired. Reconnect with new credentials.",
    "SubscriptionRequiredException": SUBSCRIPTION_MESSAGE,
}
