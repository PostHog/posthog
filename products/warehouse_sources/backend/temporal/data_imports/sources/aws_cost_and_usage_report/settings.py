import re

from products.warehouse_sources.backend.types import IncrementalField

S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"
S3_SIGNING_NAME = "s3"

LIST_PAGE_SIZE = 1000
# Bytes per read when streaming a data file to disk.
DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
# Rows per batch handed to the pipeline, matching its own batcher.
ROWS_PER_BATCH = 5000

# Data Exports names each partition directory `BILLING_PERIOD=YYYY-MM`.
BILLING_PERIOD_DIRECTORY = re.compile(r"BILLING_PERIOD=(\d{4})-(\d{2})/?$")
BILLING_PERIOD_INPUT = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATA_FILE_SUFFIXES = (".parquet", ".csv.gz")
BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
DECIMAL_TYPE = re.compile(r"^decimal\((\d+),\s*(\d+)\)$")

COST_AND_USAGE = "cost_and_usage"

ENDPOINTS = (COST_AND_USAGE,)

# AWS restates whole billing periods, and the line item id is not stable between deliveries, so
# there is no key to merge on. The table is rebuilt from the latest delivery of each period.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    COST_AND_USAGE: "Every line item of the export, from the latest delivery of each billing period in range.",
}
