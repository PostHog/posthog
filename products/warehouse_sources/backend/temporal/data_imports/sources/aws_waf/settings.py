from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

WAF_API_VERSION = "2019-07-29"
TARGET_PREFIX = "AWSWAF_20190729"
PAGE_SIZE = 100


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

ENDPOINTS = tuple(AWS_WAF_ENDPOINTS)
ENDPOINT_DESCRIPTIONS = {name: endpoint.description for name, endpoint in AWS_WAF_ENDPOINTS.items()}
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

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
        ACCESS_DENIED_CODES, "These credentials lack AWS WAF read permissions. Grant the listed wafv2 permissions."
    ),
}
