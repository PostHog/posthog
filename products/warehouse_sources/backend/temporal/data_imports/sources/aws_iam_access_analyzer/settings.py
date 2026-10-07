from typing import Literal

from posthog.dataclasses import frozen

API_VERSION = "2019-11-01"
DEFAULT_REGION = "us-east-1"
PAGE_SIZE = 100
API_DOCS_URL = "https://docs.aws.amazon.com/access-analyzer/latest/APIReference/"
PARTITION_KEY = "created_at"
TIMESTAMP_COLUMNS = {"created_at", "updated_at", "analyzed_at", "last_resource_analyzed_at"}


@frozen
class Endpoint:
    method: Literal["GET", "POST"]
    path: str
    result_key: str
    primary_keys: tuple[str, ...]
    description: str


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
}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant access-analyzer:ListAnalyzers, access-analyzer:ListFindings, and access-analyzer:ListArchiveRules for the tables you select.",
    "AccessDeniedException": "AWS denied access. Grant access-analyzer:ListAnalyzers, access-analyzer:ListFindings, and access-analyzer:ListArchiveRules for the tables you select.",
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
