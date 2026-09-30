import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.conf import settings

import structlog
import botocore.exceptions

from products.data_warehouse.backend.facade.api import ensure_bucket_exists, get_s3_client
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

logger = structlog.get_logger(__name__)


@dataclass
class BatchWriteResult:
    """Result of writing a batch to S3."""

    s3_path: str
    row_count: int
    byte_size: int
    batch_index: int
    timestamp_ns: int = field(default_factory=time.time_ns)


def strip_s3_protocol(s3_path: str) -> str:
    """Remove the s3:// protocol prefix from a path."""
    return s3_path.replace("s3://", "")


def get_date_partition(dt: datetime) -> str:
    """Return the given datetime's UTC date as a Hive-style partition segment (dt=YYYY-MM-DD)."""
    return f"dt={dt.astimezone(UTC).strftime('%Y-%m-%d')}"


def get_base_folder(team_id: int, schema_id: str, run_uuid: str, date_partition: str) -> str:
    """Get the base S3 folder path for a pipeline run."""
    return (
        f"s3://{settings.DATAWAREHOUSE_BUCKET}/data_pipelines_extract/{date_partition}/{team_id}/{schema_id}/{run_uuid}"
    )


def get_data_folder(base_folder: str) -> str:
    """Get the data folder path within a base folder."""
    return f"{base_folder}/data"


def _is_forbidden(error: botocore.exceptions.ClientError) -> bool:
    """Whether the S3 API refused the call because of credentials or a bucket policy.

    HeadBucket sends no body, so botocore has only the HTTP status to put in "Code" and reports
    the refusal as "403" instead of AccessDenied. Stores that do return a body keep the named
    code, so both forms have to be recognized.
    """
    if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 403:
        return True
    return error.response.get("Error", {}).get("Code") in ("403", "AccessDenied", "Forbidden")


def ensure_bucket() -> None:
    """Ensure the S3 bucket exists for local development."""
    if settings.USE_LOCAL_SETUP:
        if (
            not settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
            or not settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET
            or not settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION
        ):
            raise KeyError(
                "Missing env vars for data warehouse. Required vars: DATAWAREHOUSE_LOCAL_ACCESS_KEY, "
                "DATAWAREHOUSE_LOCAL_ACCESS_SECRET, DATAWAREHOUSE_LOCAL_BUCKET_REGION"
            )

        try:
            ensure_bucket_exists(
                settings.BUCKET_URL,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )
        except botocore.exceptions.ClientError as error:
            if not _is_forbidden(error):
                raise
            # ensure_bucket_exists already retried the refusal to let a still-registering object
            # store finish its credential bootstrap, so one that arrives here comes from the
            # credentials or the bucket policy and every later attempt gets the same answer.
            # NonRetryableException stops the activity retries and keeps a known configuration
            # failure out of error tracking.
            logger.warning("ensure_bucket_forbidden", bucket=settings.DATAWAREHOUSE_BUCKET)
            raise NonRetryableException(
                "Couldn't reach the data warehouse storage with the configured credentials. "
                "Contact support if this keeps happening."
            ) from error


def cleanup_folder(folder_path: str) -> None:
    """Delete an S3 folder and all its contents."""
    s3 = get_s3_client()
    folder_without_protocol = strip_s3_protocol(folder_path)
    try:
        s3.delete(folder_without_protocol, recursive=True)
        logger.debug("cleanup_folder_success", folder=folder_path)
    except FileNotFoundError:
        logger.debug("cleanup_folder_not_found", folder=folder_path)
