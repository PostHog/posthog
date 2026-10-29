from datetime import timedelta

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

WAF_API_VERSION = "2019-07-29"
TARGET_PREFIX = "AWSWAF_20190729"
PAGE_SIZE = 100


@frozen
class AwsService:
    signing_name: str
    target_prefix: str
    content_type: str


WAFV2_SERVICE = AwsService(signing_name="wafv2", target_prefix=TARGET_PREFIX, content_type="application/x-amz-json-1.1")
CLOUDWATCH_SERVICE = AwsService(
    signing_name="monitoring", target_prefix="GraniteServiceVersion20100801", content_type="application/x-amz-json-1.0"
)


@frozen
class WafEndpoint:
    list_operation: str
    list_key: str
    get_operation: str
    object_key: str
    description: str


AWS_WAF_ENDPOINTS: dict[str, WafEndpoint] = {
    "web_acls": WafEndpoint(
        list_operation="ListWebACLs",
        list_key="WebACLs",
        get_operation="GetWebACL",
        object_key="WebACL",
        description="Web access control lists, with their rules, default actions, and visibility settings.",
    ),
    "rule_groups": WafEndpoint(
        list_operation="ListRuleGroups",
        list_key="RuleGroups",
        get_operation="GetRuleGroup",
        object_key="RuleGroup",
        description="Rule groups that you manage, with their rules and capacity settings.",
    ),
    "ip_sets": WafEndpoint(
        list_operation="ListIPSets",
        list_key="IPSets",
        get_operation="GetIPSet",
        object_key="IPSet",
        description="IP sets with their IP version and address ranges in CIDR notation.",
    ),
    "regex_pattern_sets": WafEndpoint(
        list_operation="ListRegexPatternSets",
        list_key="RegexPatternSets",
        get_operation="GetRegexPatternSet",
        object_key="RegexPatternSet",
        description="Sets of regular expressions that rules use to inspect web requests.",
    ),
}

MANAGED_RULE_GROUPS = "managed_rule_groups"
WEB_ACL_RESOURCES = "protected_resources"
SAMPLED_REQUESTS = "sampled_requests"
REQUEST_METRICS = "request_metrics"

TABLE_DESCRIPTIONS = {
    MANAGED_RULE_GROUPS: "Managed rule groups available to the account, with their rules, labels, and capacity.",
    WEB_ACL_RESOURCES: "Regional resources that each web ACL protects, such as load balancers and API stages.",
    SAMPLED_REQUESTS: "Samples of recent web requests that matched web ACL rules, with the action AWS WAF took.",
    REQUEST_METRICS: "Hourly CloudWatch request counts for web ACLs, rules, and labels, such as allowed and blocked requests.",
}
TABLE_PERMISSIONS = {
    **{
        name: (f"wafv2:{endpoint.list_operation}", f"wafv2:{endpoint.get_operation}")
        for name, endpoint in AWS_WAF_ENDPOINTS.items()
    },
    MANAGED_RULE_GROUPS: ("wafv2:ListAvailableManagedRuleGroups", "wafv2:DescribeManagedRuleGroup"),
    WEB_ACL_RESOURCES: ("wafv2:ListWebACLs", "wafv2:ListResourcesForWebACL"),
    SAMPLED_REQUESTS: ("wafv2:ListWebACLs", "wafv2:GetWebACL", "wafv2:GetSampledRequests"),
    REQUEST_METRICS: ("cloudwatch:ListMetrics", "cloudwatch:GetMetricData"),
}


@frozen
class ListCall:
    operation: str
    key: str


LIST_CALLS = {
    **{
        name: ListCall(operation=endpoint.list_operation, key=endpoint.list_key)
        for name, endpoint in AWS_WAF_ENDPOINTS.items()
    },
    MANAGED_RULE_GROUPS: ListCall(operation="ListAvailableManagedRuleGroups", key="ManagedRuleGroups"),
}

PRIMARY_KEYS = {
    **dict.fromkeys(AWS_WAF_ENDPOINTS, ["arn"]),
    MANAGED_RULE_GROUPS: ["vendor_name", "name"],
    WEB_ACL_RESOURCES: ["web_acl_arn", "resource_arn"],
    SAMPLED_REQUESTS: ["id"],
    REQUEST_METRICS: ["metric_id", "timestamp"],
}

ENDPOINTS = (*AWS_WAF_ENDPOINTS, *TABLE_DESCRIPTIONS)
ENDPOINT_DESCRIPTIONS = {
    **{name: endpoint.description for name, endpoint in AWS_WAF_ENDPOINTS.items()},
    **TABLE_DESCRIPTIONS,
}
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    SAMPLED_REQUESTS: [incremental_field("timestamp")],
    REQUEST_METRICS: [incremental_field("timestamp")],
}
# GetSampledRequests only reaches 3 hours back, longer than the default sync interval, so users opt in and pick a schedule.
SHOULD_SYNC_DEFAULT = {SAMPLED_REQUESTS: False}
# Hourly datapoints can still change while CloudWatch receives late data for the current hour.
INCREMENTAL_LOOKBACK_SECONDS = {REQUEST_METRICS: 3 * 3600}

# ListResourcesForWebACL defaults to load balancers, so each regional resource type is listed explicitly.
PROTECTED_RESOURCE_TYPES = (
    "APPLICATION_LOAD_BALANCER",
    "API_GATEWAY",
    "APPSYNC",
    "COGNITO_USER_POOL",
    "APP_RUNNER_SERVICE",
    "VERIFIED_ACCESS_INSTANCE",
    "AMPLIFY",
    "AGENTCORE_GATEWAY",
)

SAMPLED_REQUESTS_MAX_ITEMS = 500
SAMPLED_REQUESTS_WINDOW = timedelta(hours=3)
# End-user credentials in sampled request headers are not copied into the warehouse.
REDACTED_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "api-key",
        "x-api-key",
        "x-auth-token",
        "x-session-token",
        "x-csrf-token",
        "x-xsrf-token",
        "x-amz-security-token",
    }
)

METRICS_NAMESPACE = "AWS/WAFV2"
METRICS_PERIOD_SECONDS = 3600
# CloudWatch keeps hourly datapoints for 455 days.
METRICS_HISTORY = timedelta(days=455)
METRICS_PER_REQUEST = 500

ACCESS_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException", "WAFUnauthorizedOperationException"})
ERROR_MESSAGES = {
    "UnrecognizedClientException": "AWS rejected the access key. Check the access key ID and secret access key.",
    "InvalidClientTokenId": "AWS rejected the access key. Check the access key ID and session token.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "ExpiredTokenException": "The AWS session token has expired. Connect again with new credentials.",
    "ExpiredToken": "The AWS session token has expired. Connect again with new credentials.",
    "OptInRequired": "Enable AWS WAF for this account before you connect this source.",
    "SubscriptionRequiredException": "Enable the required AWS subscription before you connect this source.",
    **dict.fromkeys(
        ACCESS_DENIED_CODES,
        "These credentials lack the AWS read permissions for this table. Grant the permissions listed in the source setup.",
    ),
}
