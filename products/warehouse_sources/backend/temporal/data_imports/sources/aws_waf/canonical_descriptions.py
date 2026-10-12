from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

COMMON_COLUMNS = {
    "arn": "Amazon Resource Name that uniquely identifies the resource.",
    "id": "Identifier assigned by AWS WAF when the resource is created.",
    "name": "Resource name assigned at creation.",
    "description": "Description of the resource.",
    "region": "AWS region used to read the resource. CloudFront resources use us-east-1.",
    "scope": "Resource scope: REGIONAL or CLOUDFRONT.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "web_acls": {
        "description": "Web access control lists that inspect requests to protected AWS resources.",
        "docs_url": "https://docs.aws.amazon.com/waf/latest/APIReference/API_GetWebACL.html",
        "columns": {
            **COMMON_COLUMNS,
            "rules": "Rules that inspect and control web requests.",
            "default_action": "Action applied when no rule determines the request action.",
            "capacity": "Web ACL capacity units used by the rules.",
            "visibility_config": "Settings for CloudWatch metrics and request sampling.",
            "managed_by_firewall_manager": "Whether AWS Firewall Manager manages the web ACL.",
        },
    },
    "rule_groups": {
        "description": "Reusable groups of rules that you manage for web request inspection.",
        "docs_url": "https://docs.aws.amazon.com/waf/latest/APIReference/API_GetRuleGroup.html",
        "columns": {
            **COMMON_COLUMNS,
            "rules": "Rules included in the group.",
            "capacity": "Web ACL capacity units reserved for the rule group.",
            "visibility_config": "Settings for CloudWatch metrics and request sampling.",
            "available_labels": "Labels that rules in this group can add to matching requests.",
            "consumed_labels": "Labels that rules in this group can match.",
        },
    },
    "ip_sets": {
        "description": "Reusable IP address sets referenced by web ACL rules and rule groups.",
        "docs_url": "https://docs.aws.amazon.com/waf/latest/APIReference/API_GetIPSet.html",
        "columns": {
            **COMMON_COLUMNS,
            "ip_address_version": "IP address family: IPV4 or IPV6.",
            "addresses": "IP addresses and ranges in CIDR notation.",
        },
    },
    "regex_pattern_sets": {
        "description": "Reusable sets of regular expressions for web request inspection.",
        "docs_url": "https://docs.aws.amazon.com/waf/latest/APIReference/API_GetRegexPatternSet.html",
        "columns": {
            **COMMON_COLUMNS,
            "regular_expression_list": "Regular expressions used to match web request components.",
        },
    },
}
