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
    names_only: bool = False
    paginated: bool = True
    missing_is_empty: bool = False


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
    "crawls": GlueEndpoint(
        operation="ListCrawls",
        result_key="Crawls",
        primary_keys=("region", "crawler_name", "crawl_id"),
        parent="crawlers",
        timestamp_columns=("start_time", "end_time"),
    ),
    "table_versions": GlueEndpoint(
        operation="GetTableVersions",
        result_key="TableVersions",
        primary_keys=("region", "database_name", "table_name", "version_id"),
        parent="tables",
    ),
    "workflow_runs": GlueEndpoint(
        operation="GetWorkflowRuns",
        result_key="Runs",
        primary_keys=("region", "name", "workflow_run_id"),
        parent="workflows",
        timestamp_columns=("started_on", "completed_on"),
    ),
    "data_quality_results": GlueEndpoint(
        operation="ListDataQualityResults",
        result_key="Results",
        primary_keys=("region", "result_id"),
        timestamp_columns=("started_on",),
    ),
    "data_quality_results_v2": GlueEndpoint(
        operation="ListDataQualityResultsV2",
        result_key="Results",
        primary_keys=("region", "result_id"),
        timestamp_columns=("result_published_on",),
    ),
    "column_statistics": GlueEndpoint(
        operation="GetColumnStatisticsForTable",
        result_key="ColumnStatisticsList",
        primary_keys=("region", "database_name", "table_name", "column_name"),
        parent="tables",
        timestamp_columns=("analyzed_time",),
        paginated=False,
    ),
    "table_optimizer_runs": GlueEndpoint(
        operation="ListTableOptimizerRuns",
        result_key="TableOptimizerRuns",
        primary_keys=("region", "database_name", "table_name", "type", "start_timestamp"),
        parent="tables",
        timestamp_columns=("start_timestamp", "end_timestamp"),
        missing_is_empty=True,
    ),
    "sessions": GlueEndpoint(
        operation="ListSessions",
        result_key="Sessions",
        primary_keys=("region", "id"),
        timestamp_columns=("created_on", "completed_on"),
    ),
}

# GetColumnStatisticsForTable accepts at most 100 column names per request.
COLUMN_STATISTICS_BATCH_SIZE = 100
TABLE_OPTIMIZER_TYPES = ("compaction", "retention", "orphan_file_deletion")

# ListWorkflows returns only names, so it feeds workflow_runs without being a table of its own.
PARENT_ENDPOINTS: dict[str, GlueEndpoint] = {
    "workflows": GlueEndpoint(
        operation="ListWorkflows",
        result_key="Workflows",
        primary_keys=("region", "name"),
        page_size=25,
        names_only=True,
    ),
}

ENDPOINT_DESCRIPTIONS = {
    "databases": "Databases in the account's default Data Catalog.",
    "tables": "Table definitions, columns, and storage metadata for each database.",
    "partitions": "Partition values and storage metadata for each table.",
    "jobs": "Job definitions and execution settings.",
    "job_runs": "Job execution history, status, duration, and resource usage.",
    "crawlers": "Crawler settings, state, and the latest crawl result.",
    "crawls": "Crawl history for each crawler, including duration, status, and DPU usage.",
    "table_versions": "Schema and metadata history for each catalog table.",
    "workflow_runs": "Workflow run history, status, timing, and action statistics.",
    "data_quality_results": "Data quality evaluation runs, with the evaluated table and the job run.",
    "data_quality_results_v2": "Data quality results published from any supported engine, with the evaluated table and run context.",
    "column_statistics": "Column statistics for each catalog table, such as null counts, distinct values, and value ranges.",
    "table_optimizer_runs": "Compaction, snapshot retention, and orphan file deletion runs for each Iceberg table.",
    "sessions": "Interactive sessions, with status, duration, and compute use.",
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
