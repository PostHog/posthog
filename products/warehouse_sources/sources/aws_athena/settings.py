from typing import Literal

AwsService = Literal["athena", "glue"]

ATHENA_SERVICE: AwsService = "athena"
GLUE_SERVICE: AwsService = "glue"

# The catalog Glue-backed databases live in. Federated catalogs are not supported yet.
DATA_CATALOG = "AwsDataCatalog"
DEFAULT_WORKGROUP = "primary"

# GetQueryResults returns at most 1,000 rows per call; GetTables at most 100 tables.
RESULTS_PAGE_SIZE = 1000
GLUE_PAGE_SIZE = 100

# Polling backs off from 1 to 10 seconds. A query that has not finished after an hour is given up,
# matching the longest DML timeout most workgroups allow.
POLL_INITIAL_SECONDS = 1.0
POLL_MAX_SECONDS = 10.0
QUERY_DEADLINE_SECONDS = 60 * 60


# The IAM actions this source calls. A role session can use only these.
# Athena runs the query as the caller and writes the results to the workgroup's S3 location.
AWS_SESSION_ACTIONS = (
    "athena:GetQueryExecution",
    "athena:GetQueryResults",
    "athena:GetWorkGroup",
    "athena:StartQueryExecution",
    "athena:StopQueryExecution",
    "glue:BatchGetPartition",
    "glue:GetDatabase",
    "glue:GetPartition",
    "glue:GetPartitions",
    "glue:GetTable",
    "glue:GetTables",
    "kms:Decrypt",
    "kms:GenerateDataKey",
    "s3:AbortMultipartUpload",
    "s3:GetBucketLocation",
    "s3:GetObject",
    "s3:ListBucket",
    "s3:ListBucketMultipartUploads",
    "s3:ListMultipartUploadParts",
    "s3:PutObject",
)
