from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

MACIE_API_VERSION = "2020-01-01"
API_DOCS_URL = "https://docs.aws.amazon.com/macie/latest/APIReference/"


@frozen
class MacieEndpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    page_size: int = 50
    timestamp_columns: tuple[str, ...] = ()


MACIE_ENDPOINTS = {
    "findings": MacieEndpoint(
        operation="ListFindings",
        result_key="findingIds",
        primary_keys=("region", "account_id", "id"),
        timestamp_columns=("created_at", "updated_at"),
    ),
    "buckets": MacieEndpoint(
        operation="DescribeBuckets",
        result_key="buckets",
        primary_keys=("bucket_arn",),
        timestamp_columns=("bucket_created_at", "last_updated", "last_automated_discovery_time"),
    ),
    "classification_jobs": MacieEndpoint(
        operation="ListClassificationJobs",
        result_key="items",
        primary_keys=("region", "job_id"),
        timestamp_columns=("created_at",),
    ),
    "members": MacieEndpoint(
        operation="ListMembers",
        result_key="members",
        primary_keys=("region", "account_id"),
        page_size=25,
        timestamp_columns=("invited_at", "updated_at"),
    ),
}
ENDPOINTS = tuple(MACIE_ENDPOINTS)
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {"findings": [incremental_field("updated_at")]}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Security and sensitive data findings, with affected resources and classification details.",
    "buckets": "S3 bucket inventory, with security settings, object counts, and discovery coverage.",
    "classification_jobs": "Sensitive data discovery jobs, with their status and bucket selection settings.",
    "members": "Accounts associated with the Macie administrator, including former members.",
}

PERMISSION_MESSAGE = (
    "Grant the required Macie read permissions: macie2:ListFindings, macie2:GetFindings, "
    "macie2:DescribeBuckets, macie2:ListClassificationJobs, and macie2:ListMembers. "
    "Enable Macie in the selected region."
)
ERROR_MESSAGES = {
    "AccessDenied": PERMISSION_MESSAGE,
    "UnrecognizedClientException": "AWS rejected the access key. Check the access key ID and secret access key.",
    "InvalidClientTokenId": "AWS rejected the access key. Check the access key ID and secret access key.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and session token.",
    "ExpiredToken": "The AWS session token expired. Enter new credentials.",
    "SubscriptionRequiredException": "Enable Amazon Macie in the selected AWS account and region.",
    "not subscribed": "Enable Amazon Macie in the selected AWS account and region.",
    "not enabled": "Enable Amazon Macie in the selected AWS account and region.",
}
