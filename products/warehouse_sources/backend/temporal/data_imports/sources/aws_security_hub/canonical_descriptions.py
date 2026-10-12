from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "findings": {
        "description": "Security findings in AWS Security Finding Format, including affected resources and compliance results.",
        "docs_url": "https://docs.aws.amazon.com/securityhub/1.0/APIReference/API_AwsSecurityFinding.html",
        "columns": {
            "id": "The finding identifier assigned by its product.",
            "product_arn": "The ARN of the product that generated the finding.",
            "aws_account_id": "The AWS account that owns the finding.",
            "region": "The AWS region where the finding originated.",
            "created_at": "When the product created the finding.",
            "updated_at": "When the product last updated the finding.",
            "processed_at": "When Security Hub last processed the finding.",
            "title": "A short title for the finding.",
            "description": "Details of the finding.",
            "severity": "The severity assigned to the finding.",
            "compliance": "The compliance status and related security controls.",
            "resources": "The resources associated with the finding.",
            "workflow": "The investigation status of the finding.",
            "record_state": "Whether the finding is active or archived.",
        },
    },
    "standards": {
        "description": "Security standards available in AWS Security Hub CSPM.",
        "docs_url": "https://docs.aws.amazon.com/securityhub/1.0/APIReference/API_Standard.html",
        "columns": {
            "standards_arn": "The ARN of the security standard.",
            "name": "The name of the standard.",
            "description": "A description of the standard.",
            "enabled_by_default": "Whether Security Hub enables the standard by default.",
            "standards_managed_by": "The company and product that manage the standard.",
        },
    },
    "enabled_standards": {
        "description": "Security standards enabled for the account in the configured region.",
        "docs_url": "https://docs.aws.amazon.com/securityhub/1.0/APIReference/API_StandardsSubscription.html",
        "columns": {
            "standards_subscription_arn": "The ARN of the enabled standard subscription.",
            "standards_arn": "The ARN of the security standard.",
            "standards_status": "The status of the standard subscription.",
            "standards_status_reason": "The reason for the subscription status.",
            "standards_input": "Input parameters for the standard subscription.",
            "standards_controls_updatable": "Whether controls in this subscription can be updated.",
        },
    },
    "insights": {
        "description": "Custom insights that group findings using filters. This table excludes AWS managed insights.",
        "docs_url": "https://docs.aws.amazon.com/securityhub/1.0/APIReference/API_Insight.html",
        "columns": {
            "insight_arn": "The ARN of the insight.",
            "name": "The name of the insight.",
            "filters": "The filters that select findings for the insight.",
            "group_by_attribute": "The finding attribute used to group the results.",
        },
    },
}
