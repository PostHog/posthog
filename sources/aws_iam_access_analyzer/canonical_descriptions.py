from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "analyzers": {
        "description": "Access analyzers in the configured AWS region.",
        "docs_url": "https://docs.aws.amazon.com/access-analyzer/latest/APIReference/API_AnalyzerSummary.html",
        "columns": {
            "arn": "The Amazon Resource Name (ARN) of the analyzer.",
            "name": "The analyzer name.",
            "type": "The analyzer type and its account or organization scope.",
            "status": "The current analyzer status.",
            "created_at": "The time when AWS created the analyzer.",
            "last_resource_analyzed": "The ARN of the most recently analyzed resource.",
            "last_resource_analyzed_at": "The time of the most recent resource analysis.",
            "configuration": "The configuration for internal or unused access analysis.",
            "status_reason": "The reason for the current analyzer status.",
            "tags": "Tags attached to the analyzer.",
            "region": "The AWS region queried by this source.",
        },
    },
    "findings": {
        "description": "Finding summaries for external, internal, and unused access from each analyzer.",
        "docs_url": "https://docs.aws.amazon.com/access-analyzer/latest/APIReference/API_FindingSummaryV2.html",
        "columns": {
            "id": "The finding ID within the analyzer.",
            "analyzer_arn": "The ARN of the analyzer that returned this finding.",
            "finding_type": "The type of access that the finding identifies.",
            "resource": "The ARN of the resource associated with the finding.",
            "resource_type": "The AWS resource type.",
            "resource_owner_account": "The AWS account that owns the resource.",
            "status": "The finding status: ACTIVE, ARCHIVED, or RESOLVED.",
            "created_at": "The time when AWS created the finding.",
            "updated_at": "The time when AWS last updated the finding.",
            "analyzed_at": "The time of the analysis that generated the finding.",
            "error": "An error that prevented the analysis.",
            "region": "The AWS region queried by this source.",
        },
    },
    "archive_rules": {
        "description": "Rules that automatically archive matching findings for each analyzer.",
        "docs_url": "https://docs.aws.amazon.com/access-analyzer/latest/APIReference/API_ArchiveRuleSummary.html",
        "columns": {
            "rule_name": "The rule name within the analyzer.",
            "analyzer_arn": "The ARN of the analyzer that owns this rule.",
            "filter": "The conditions that a finding must meet for automatic archiving.",
            "created_at": "The time when AWS created the rule.",
            "updated_at": "The time when AWS last updated the rule.",
            "region": "The AWS region queried by this source.",
        },
    },
}
