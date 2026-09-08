from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# AWS Organizations is a global service: the docs state there is "a single global endpoint for
# all of the AWS Regions in each partition", so both the host and the SigV4 signing region are
# fixed rather than user-configurable.
ORGANIZATIONS_ENDPOINT_URL = "https://organizations.us-east-1.amazonaws.com/"
SIGNING_REGION = "us-east-1"
SIGNING_NAME = "organizations"

CONTENT_TYPE = "application/x-amz-json-1.1"

# Service model version. It is carried in the `X-Amz-Target` header of every request
# (`AWSOrganizationsV20161128.<Operation>`), so this is a real pin rather than a label.
ORGANIZATIONS_API_VERSION = "2016-11-28"
TARGET_PREFIXES: dict[str, str] = {ORGANIZATIONS_API_VERSION: "AWSOrganizationsV20161128"}

REQUEST_TIMEOUT_SECONDS = 60

# Every paginated Organizations operation caps `MaxResults` at 20.
MAX_RESULTS = 20

MAX_RETRY_ATTEMPTS = 6
RETRY_INITIAL_WAIT_SECONDS = 1.0
RETRY_MAX_WAIT_SECONDS = 60.0

# Organizations returns throttling and internal errors as HTTP 400 with the code in the body, so
# the transport's status-code retries never see them. They are retried in-source instead.
RETRYABLE_ERROR_CODES = frozenset(
    {
        "ConcurrentModificationException",
        "ServiceException",
        "TooManyRequestsException",
    }
)

# Codes that mean the key itself is bad, as opposed to a valid key missing an IAM permission.
CREDENTIAL_ERROR_CODES = (
    "UnrecognizedClientException",
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
    "InvalidSignatureException",
    "ExpiredTokenException",
    "ExpiredToken",
    "IncompleteSignature",
    "MissingAuthenticationToken",
)

# `Filter` is required on ListPolicies and takes one policy type per call, so the policies table
# is one walk per type. Kept in the docs' `Valid Values` order.
POLICY_FILTERS = (
    "SERVICE_CONTROL_POLICY",
    "RESOURCE_CONTROL_POLICY",
    "TAG_POLICY",
    "BACKUP_POLICY",
    "AISERVICES_OPT_OUT_POLICY",
    "CHATBOT_POLICY",
    "DECLARATIVE_POLICY_EC2",
    "SECURITYHUB_POLICY",
    "INSPECTOR_POLICY",
    "UPGRADE_ROLLOUT_POLICY",
    "BEDROCK_POLICY",
    "S3_POLICY",
    "NETWORK_SECURITY_DIRECTOR_POLICY",
)


@dataclass(frozen=True)
class AwsOrganizationsEndpointConfig:
    name: str
    # Operation that produces this table's rows. Fan-out tables name their child operation here;
    # the parents they iterate are listed by the transport.
    operation: str
    primary_key: list[str] | None
    # Response key holding the list of items. `None` for single-object operations.
    result_key: str | None = None
    # Top-level response member wrapping a single-object operation's row.
    object_key: str | None = None
    # `MaxResults` per request. `None` for operations that don't accept it
    # (DescribeOrganization, ListTagsForResource).
    page_size: int | None = None
    # Flattened columns holding epoch-seconds timestamps, parsed into datetimes.
    timestamp_columns: tuple[str, ...] = ()
    # Response members deliberately not stored, with the reason on each entry below.
    drop_keys: frozenset[str] = field(default_factory=frozenset)
    # IAM actions a sync of this table calls, for the permission messages.
    iam_actions: tuple[str, ...] = ()


AWS_ORGANIZATIONS_ENDPOINTS: dict[str, AwsOrganizationsEndpointConfig] = {
    "accounts": AwsOrganizationsEndpointConfig(
        name="accounts",
        operation="ListAccounts",
        primary_key=["id"],
        result_key="Accounts",
        page_size=MAX_RESULTS,
        timestamp_columns=("joined_timestamp",),
        # AWS retires the `Status` response member on September 9, 2026 and recommends `State`,
        # which carries the same value.
        drop_keys=frozenset({"Status"}),
        iam_actions=("organizations:ListAccounts",),
    ),
    "organization": AwsOrganizationsEndpointConfig(
        name="organization",
        operation="DescribeOrganization",
        primary_key=["id"],
        object_key="Organization",
        # `AvailablePolicyTypes` is deprecated and only ever reports service control policies.
        # `roots.policy_types` is the supported way to read which policy types are enabled.
        drop_keys=frozenset({"AvailablePolicyTypes"}),
        iam_actions=("organizations:DescribeOrganization",),
    ),
    "organizational_units": AwsOrganizationsEndpointConfig(
        name="organizational_units",
        operation="ListOrganizationalUnitsForParent",
        primary_key=["id"],
        result_key="OrganizationalUnits",
        page_size=MAX_RESULTS,
        iam_actions=("organizations:ListRoots", "organizations:ListOrganizationalUnitsForParent"),
    ),
    "policies": AwsOrganizationsEndpointConfig(
        name="policies",
        operation="ListPolicies",
        primary_key=["id"],
        result_key="Policies",
        page_size=MAX_RESULTS,
        iam_actions=("organizations:ListPolicies",),
    ),
    "resource_tags": AwsOrganizationsEndpointConfig(
        name="resource_tags",
        operation="ListTagsForResource",
        primary_key=["resource_id", "key"],
        result_key="Tags",
        iam_actions=(
            "organizations:ListAccounts",
            "organizations:ListRoots",
            "organizations:ListOrganizationalUnitsForParent",
            "organizations:ListPolicies",
            "organizations:ListTagsForResource",
        ),
    ),
    "roots": AwsOrganizationsEndpointConfig(
        name="roots",
        operation="ListRoots",
        primary_key=["id"],
        result_key="Roots",
        page_size=MAX_RESULTS,
        iam_actions=("organizations:ListRoots",),
    ),
}

ENDPOINTS = tuple(AWS_ORGANIZATIONS_ENDPOINTS.keys())

# Organizations exposes no server-side time filter on any of these operations, so every table
# is a full refresh. The volumes are small: accounts, OUs and policies are all bounded by
# per-organization quotas.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "accounts": "Every AWS account in the organization, with its name, email, state, and the time it joined.",
    "organization": "The organization itself: its ID, feature set, and management account. One row per sync.",
    "organizational_units": "Organizational units in the account hierarchy, each with the parent it sits under.",
    "policies": "Policies in the organization, one row per policy, across every policy type the organization supports.",
    "resource_tags": "Tags attached to accounts, roots, organizational units, and policies. One row per tag.",
    "roots": "Roots of the organization, with the policy types enabled on each.",
}
