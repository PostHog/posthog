from posthog.dataclasses import frozen

GLUE_API_VERSION = "2017-03-31"
TARGET_PREFIXES = {GLUE_API_VERSION: "AWSGlue"}
CONTENT_TYPE = "application/x-amz-json-1.1"
REQUEST_TIMEOUT_SECONDS = 60


@frozen
class GlueEndpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    parent: str | None = None
    page_size: int = 100
    timestamp_columns: tuple[str, ...] = ()


ENDPOINTS: dict[str, GlueEndpoint] = {
    "databases": GlueEndpoint(
        operation="GetDatabases",
        result_key="DatabaseList",
        primary_keys=("region", "name"),
        timestamp_columns=("create_time",),
    ),
    "tables": GlueEndpoint(
        operation="GetTables",
        result_key="TableList",
        primary_keys=("region", "database_name", "name"),
        parent="databases",
        timestamp_columns=("create_time", "update_time", "last_access_time", "last_analyzed_time"),
    ),
    "partitions": GlueEndpoint(
        operation="GetPartitions",
        result_key="Partitions",
        primary_keys=("region", "database_name", "table_name", "partition_values"),
        parent="tables",
        timestamp_columns=("creation_time", "last_access_time", "last_analyzed_time"),
    ),
    "jobs": GlueEndpoint(
        operation="GetJobs",
        result_key="Jobs",
        primary_keys=("region", "name"),
        timestamp_columns=("created_on", "last_modified_on"),
    ),
    "job_runs": GlueEndpoint(
        operation="GetJobRuns",
        result_key="JobRuns",
        primary_keys=("region", "job_name", "id"),
        parent="jobs",
        timestamp_columns=("started_on", "last_modified_on", "completed_on"),
    ),
    "crawlers": GlueEndpoint(
        operation="GetCrawlers",
        result_key="Crawlers",
        primary_keys=("region", "name"),
        timestamp_columns=("creation_time", "last_updated"),
    ),
}

ENDPOINT_DESCRIPTIONS = {
    "databases": "Databases in the account's default Data Catalog.",
    "tables": "Table definitions, columns, and storage metadata for each database.",
    "partitions": "Partition values and storage metadata for each table.",
    "jobs": "Job definitions and execution settings.",
    "job_runs": "Job execution history, status, duration, and resource usage.",
    "crawlers": "Crawler settings, state, and the latest crawl result.",
}

ERROR_MESSAGES = {
    "AccessDeniedException": "AWS denied access. Grant the required Glue read permissions and check Lake Formation permissions.",
    "AccessDenied": "AWS denied access. Grant the required Glue read permissions and check Lake Formation permissions.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Enter the correct secret access key.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "ExpiredTokenException": "The AWS session token expired. Enter new credentials.",
    "ExpiredToken": "The AWS session token expired. Enter new credentials.",
    "OptInRequired": "Enable AWS Glue for this account and region, then reconnect.",
    "SubscriptionRequiredException": "Enable AWS Glue for this account and region, then reconnect.",
    "SubscriptionRequired": "Enable AWS Glue for this account and region, then reconnect.",
}

BODY_RETRY_CODES = frozenset(
    {
        "ThrottlingException",
        "Throttling",
        "TooManyRequestsException",
        "OperationTimeoutException",
        "FederationSourceRetryableException",
    }
)
