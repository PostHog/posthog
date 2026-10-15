from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

GUARDDUTY_API_VERSION = "2017-11-28"
MAX_RESULTS = 50


@frozen
class GuarddutyEndpoint:
    operation: str
    result_key: str | None
    primary_keys: tuple[str, ...]
    iam_actions: tuple[str, ...]


ENDPOINTS = {
    "findings": GuarddutyEndpoint(
        operation="ListFindings",
        result_key="findingIds",
        primary_keys=("arn",),
        iam_actions=("guardduty:ListDetectors", "guardduty:ListFindings", "guardduty:GetFindings"),
    ),
    "detectors": GuarddutyEndpoint(
        operation="GetDetector",
        result_key=None,
        primary_keys=("region", "source_detector_id"),
        iam_actions=("guardduty:ListDetectors", "guardduty:GetDetector"),
    ),
    "members": GuarddutyEndpoint(
        operation="ListMembers",
        result_key="members",
        primary_keys=("region", "source_detector_id", "account_id"),
        iam_actions=("guardduty:ListDetectors", "guardduty:ListMembers"),
    ),
}

INCREMENTAL_FIELDS = {"findings": [incremental_field("updated_at")]}
ENDPOINT_DESCRIPTIONS = {
    "findings": "Threat findings, including severity, affected resources, and detection details.",
    "detectors": "Detector status, enabled features, and configuration in the selected region.",
    "members": "Member accounts and their relationship with the GuardDuty administrator account.",
}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the GuardDuty read permissions listed in the source setup.",
    "ForbiddenException": "AWS denied access. Grant the GuardDuty read permissions listed in the source setup.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "ExpiredToken": "The AWS session token expired. Reconnect with current credentials.",
    "SubscriptionRequiredException": "Enable GuardDuty in the selected AWS region, then reconnect.",
}
