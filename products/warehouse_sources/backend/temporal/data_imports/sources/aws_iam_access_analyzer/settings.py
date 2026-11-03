from typing import Literal

from posthog.dataclasses import frozen

API_VERSION = "2019-11-01"
DEFAULT_REGION = "us-east-1"
PAGE_SIZE = 100
API_DOCS_URL = "https://docs.aws.amazon.com/access-analyzer/latest/APIReference/"
PARTITION_KEY = "created_at"
TIMESTAMP_COLUMNS = {
    "created_at",
    "updated_at",
    "analyzed_at",
    "last_resource_analyzed_at",
    "started_at",
    "completed_at",
}
EXTERNAL_ACCESS_ANALYZER_TYPES = frozenset({"ACCOUNT", "ORGANIZATION"})
UNUSED_ACCESS_ANALYZER_TYPES = frozenset({"ACCOUNT_UNUSED_ACCESS", "ORGANIZATION_UNUSED_ACCESS"})


@frozen
class Endpoint:
    method: Literal["GET", "POST"]
    path: str
    result_key: str
    primary_keys: tuple[str, ...]
    description: str
    partition_key: str | None = PARTITION_KEY
    # Analyzer types that support the endpoint. None means every type.
    analyzer_types: frozenset[str] | None = None
    # Detail endpoints make one request per finding from ListFindingsV2.
    per_finding: bool = False
    finding_types: frozenset[str] | None = None


ENDPOINTS: dict[str, Endpoint] = {
    "analyzers": Endpoint(
        method="GET",
        path="/analyzer",
        result_key="analyzers",
        primary_keys=("arn",),
        description="Access analyzers in the configured AWS region.",
    ),
    "findings": Endpoint(
        method="POST",
        path="/findingv2",
        result_key="findings",
        primary_keys=("analyzer_arn", "id"),
        description="External, internal, and unused access findings from each analyzer.",
    ),
    "archive_rules": Endpoint(
        method="GET",
        path="/analyzer/{analyzer_name}/archive-rule",
        result_key="archiveRules",
        primary_keys=("analyzer_arn", "rule_name"),
        description="Rules that automatically archive findings for each analyzer.",
    ),
    "analyzed_resources": Endpoint(
        method="POST",
        path="/analyzed-resource",
        result_key="analyzedResources",
        primary_keys=("analyzer_arn", "resource_arn"),
        description="Resources that each external access analyzer analyzed, with or without findings.",
        partition_key=None,
        # ListAnalyzedResources rejects unused and internal access analyzers.
        analyzer_types=EXTERNAL_ACCESS_ANALYZER_TYPES,
    ),
    "finding_details": Endpoint(
        method="GET",
        path="/findingv2/{id}",
        result_key="findingDetails",
        primary_keys=("analyzer_arn", "id"),
        description="Full findings with the principals, actions, and unused permissions behind each finding.",
        per_finding=True,
    ),
    "finding_recommendations": Endpoint(
        method="GET",
        path="/recommendation/{id}",
        result_key="recommendedSteps",
        primary_keys=("analyzer_arn", "finding_id"),
        description="Remediation steps for unused permission findings that already have a generated recommendation.",
        partition_key=None,
        analyzer_types=UNUSED_ACCESS_ANALYZER_TYPES,
        per_finding=True,
        finding_types=frozenset({"UnusedPermission"}),
    ),
}

ACCESS_DENIED_MESSAGE = (
    "AWS denied access. Grant access-analyzer:ListAnalyzers, access-analyzer:ListFindings, "
    "access-analyzer:ListArchiveRules, access-analyzer:ListAnalyzedResources, access-analyzer:GetFinding, "
    "and access-analyzer:GetFindingRecommendation for the tables you select."
)

ERROR_MESSAGES = {
    "AccessDenied": ACCESS_DENIED_MESSAGE,
    "AccessDeniedException": ACCESS_DENIED_MESSAGE,
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and region.",
    "ExpiredTokenException": "The AWS session token has expired. Enter new temporary credentials.",
    "ExpiredToken": "The AWS session token has expired. Enter new temporary credentials.",
    "SubscriptionRequiredException": "AWS requires a subscription. Enable IAM Access Analyzer in the selected account and region.",
    "OptInRequired": "AWS requires access to this service. Enable IAM Access Analyzer in the selected account and region.",
    "ValidationException": "AWS rejected the request. Check the selected region and resume the sync with a fresh checkpoint.",
}
