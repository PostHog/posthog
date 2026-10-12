import re

# DynamoDB's only API version. It is carried in the `X-Amz-Target` header of every request
# (`DynamoDB_20120810.<Operation>`), so this is a real pin rather than a cosmetic label.
DYNAMODB_API_VERSION = "2012-08-10"

# SigV4 service name and the regional endpoint template. The host is always AWS-owned, which
# is why `aws_region` can be a free-text field without becoming an SSRF vector.
SIGV4_SERVICE_NAME = "dynamodb"
ENDPOINT_TEMPLATE = "https://dynamodb.{region}.amazonaws.com/"

# AWS region codes are lowercase alphanumerics and hyphens (`us-east-1`, `ap-southeast-3`,
# `us-gov-west-1`). Anything else could smuggle a host or path into the endpoint.
REGION_PATTERN = re.compile(r"^[a-z0-9-]+$")

CONTENT_TYPE = "application/x-amz-json-1.0"

REQUEST_TIMEOUT_SECONDS = 60

# Scan returns at most 1 MB per call regardless of `Limit`; the cap just bounds how many items
# a single page can hold so wide rows don't build an oversized batch.
SCAN_PAGE_LIMIT = 1000
LIST_TABLES_PAGE_LIMIT = 100

MAX_RETRY_ATTEMPTS = 6
RETRY_INITIAL_WAIT_SECONDS = 1.0
RETRY_MAX_WAIT_SECONDS = 60.0

# Throttling and capacity errors come back as HTTP 400 with an error code in the body, so the
# transport's status-code retries never see them. These are retried in-source instead.
RETRYABLE_ERROR_CODES = frozenset(
    {
        "InternalServerError",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
        "ServiceUnavailable",
        "ThrottlingException",
        "TransactionInProgressException",
    }
)

_INVALID_KEY_MESSAGE = "AWS rejected your access key. Check the access key ID and secret access key, then reconnect."

# Error codes that never recover on retry, mapped to the message the user sees.
NON_RETRYABLE_ERROR_MESSAGES: dict[str, str | None] = {
    "UnrecognizedClientException": _INVALID_KEY_MESSAGE,
    "InvalidClientTokenId": _INVALID_KEY_MESSAGE,
    "InvalidSignatureException": "AWS could not verify the request signature. Check your secret access key, then reconnect.",
    "SignatureDoesNotMatch": "AWS could not verify the request signature. Check your secret access key, then reconnect.",
    "ExpiredTokenException": "Your AWS session token has expired. Enter a new one and reconnect.",
    "ExpiredToken": "Your AWS session token has expired. Enter a new one and reconnect.",
    "AccessDeniedException": "This AWS key can't read DynamoDB. Grant it dynamodb:ListTables, dynamodb:DescribeTable and dynamodb:Scan, then try again.",
    "ResourceNotFoundException": "This DynamoDB table no longer exists in the selected region. Check the table and region, then try again.",
    "ValidationException": "AWS rejected the request as invalid. Check that the region matches where your tables live.",
    "IncompleteSignature": "AWS could not verify the request signature. Check your access key ID and secret access key, then reconnect.",
    "MissingAuthenticationToken": _INVALID_KEY_MESSAGE,
}
