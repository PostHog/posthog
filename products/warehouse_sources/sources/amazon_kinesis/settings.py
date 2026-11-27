from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

KINESIS_API_VERSION = "2013-12-02"

SHARD_ID_COLUMN = "_kinesis_shard_id"
SEQUENCE_NUMBER_COLUMN = "_kinesis_sequence_number"
PARTITION_KEY_COLUMN = "_kinesis_partition_key"
ARRIVAL_TIMESTAMP_COLUMN = "_kinesis_arrival_timestamp"
RAW_DATA_COLUMN = "_kinesis_raw_data"
RAW_DATA_ENCODING_COLUMN = "_kinesis_raw_data_encoding"
VALUE_COLUMN = "value"

PRIMARY_KEYS = [SHARD_ID_COLUMN, SEQUENCE_NUMBER_COLUMN]

INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": ARRIVAL_TIMESTAMP_COLUMN,
        "type": IncrementalFieldType.DateTime,
        "field": ARRIVAL_TIMESTAMP_COLUMN,
        "field_type": IncrementalFieldType.DateTime,
    }
]

KPL_AGGREGATION_PREFIX = b"\xf3\x89\x9a\xc2"

REQUEST_TIMEOUT = (10, 60)
MAX_ATTEMPTS = 6
RETRY_BUDGET_SECONDS = 180

LIST_STREAMS_PAGE_SIZE = 100
LIST_SHARDS_PAGE_SIZE = 1000
GET_RECORDS_LIMIT = 10000
GET_RECORDS_INTERVAL_SECONDS = 0.5
# Each shard serves reads at about 2 MB/s, so a sync reads several shards at once to keep up with a
# stream whose writes add up across shards.
SHARD_READ_WORKERS = 4
SHARD_QUEUE_POLL_SECONDS = 1.0

THROTTLING_ERROR_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "LimitExceededException",
        "KMSThrottlingException",
        "ThrottlingException",
        "Throttling",
    }
)

TRANSIENT_ERROR_CODES = frozenset({"InternalFailureException", "ServiceUnavailable", "InternalFailure"})

_INVALID_KEY_MESSAGE = (
    "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active."
)
_ACCESS_DENIED_MESSAGE = (
    "These AWS credentials cannot read Kinesis. Grant kinesis:ListStreams, kinesis:DescribeStreamSummary, "
    "kinesis:ListShards, kinesis:GetShardIterator and kinesis:GetRecords to the IAM user or role."
)
_KMS_MESSAGE = (
    "Kinesis could not decrypt this stream with its KMS key. Grant kms:Decrypt on the key to the IAM user or role, "
    "and check that the key is enabled."
)

VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "UnrecognizedClientException": _INVALID_KEY_MESSAGE,
    "InvalidClientTokenId": _INVALID_KEY_MESSAGE,
    "MissingAuthenticationToken": _INVALID_KEY_MESSAGE,
    "SignatureDoesNotMatch": "AWS rejected the request signature. Re-enter the secret access key.",
    "InvalidSignatureException": "AWS rejected the request signature. Re-enter the secret access key.",
    "IncompleteSignature": "AWS rejected the request signature. Re-enter the access key ID and secret access key.",
    "ExpiredTokenException": "The AWS session token has expired. Reconnect with fresh credentials.",
    "ExpiredToken": "The AWS session token has expired. Reconnect with fresh credentials.",
    "AccessDeniedException": _ACCESS_DENIED_MESSAGE,
    "AccessDenied": _ACCESS_DENIED_MESSAGE,
    "HTTP 401": _INVALID_KEY_MESSAGE,
    "HTTP 403": _ACCESS_DENIED_MESSAGE,
}

SYNC_ERROR_MESSAGES: dict[str, str] = {
    **VALIDATION_ERROR_MESSAGES,
    "ResourceNotFoundException": (
        "This Kinesis stream no longer exists in the selected region. Check the stream and the region on the source."
    ),
    "KMSAccessDeniedException": _KMS_MESSAGE,
    "KMSDisabledException": _KMS_MESSAGE,
    "KMSInvalidStateException": _KMS_MESSAGE,
    "KMSNotFoundException": _KMS_MESSAGE,
    "KMSOptInRequired": _KMS_MESSAGE,
}

INVALID_REGION_MESSAGE = "Enter a valid AWS region, such as us-east-1."
STREAM_NOT_FOUND_MESSAGE = (
    "PostHog could not find this Kinesis stream in the selected region. Check the stream name and region."
)
NO_STREAMS_MESSAGE = (
    "PostHog connected to Kinesis but found no streams in this region. Check the region, and that these credentials "
    "can list your streams."
)
UNREACHABLE_MESSAGE = "PostHog could not reach Kinesis. Wait a moment, then try again."
