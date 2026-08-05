"""Shared plumbing for the inbox-ranking Dagster dags.

Everything here is dag-agnostic: the S3 destination (bucket, prefix, key layout), the daily
partition scheme, gating, and Parquet IO. Individual dags (dataset today, training/eval later)
live in sibling packages and import from here so they share one destination and one partition
definition.
"""

import datetime
import tempfile

import boto3
import dagster
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from posthog import settings
from posthog.dags.common import JobOwners

DATASET_VERSION = "v1"

S3_BUCKET_ENV = "INBOX_RANKING_DATASET_S3_BUCKET"

PARQUET_PART_NAME = "part-00000.parquet"

# Earliest label event worth reading: report-attributed pr_created starts 2026-04-20, and the
# other label streams start later. Also the earliest backfillable partition.
# The explicit +00:00 offset is load-bearing: HogQL's toDateTime parses bare datetime strings in
# the querying team's timezone (US/Pacific for the dogfood project), which would shift every
# label bound 7-8 hours off the UTC partition boundary. An embedded offset overrides that.
LABELS_EPOCH = "2026-04-01T00:00:00+00:00"

partition_def = dagster.DailyPartitionsDefinition(start_date="2026-04-01")

owner_tags: dict[str, str] = {"owner": JobOwners.TEAM_SELF_DRIVING.value}


def is_inbox_ranking_registered() -> bool:
    """EU report rows and embeddings are unreachable from a US dag, and labels from every region
    already land in the US dogfood project, so the whole location registers on US only."""
    return settings.CLOUD_DEPLOYMENT != "EU"


def dataset_unconfigured() -> bool:
    # On Cloud the dataset must never fall back to the shared object-storage bucket: assets skip
    # until the dedicated bucket is provisioned. Local dev falls back to the object-storage service.
    return bool(settings.CLOUD_DEPLOYMENT) and not settings.INBOX_RANKING_DATASET_S3_BUCKET


def dataset_bucket() -> str:
    return settings.INBOX_RANKING_DATASET_S3_BUCKET or settings.OBJECT_STORAGE_BUCKET


def partition_object_key(prefix: str, table: str, partition_key: str) -> str:
    return f"{prefix}/{table}/{DATASET_VERSION}/dt={partition_key}/{PARQUET_PART_NAME}"


def latest_object_key(prefix: str, table: str) -> str:
    return f"{prefix}/{table}/{DATASET_VERSION}/latest/{PARQUET_PART_NAME}"


def snapshot_bounds(partition_key: str) -> tuple[datetime.datetime, datetime.datetime]:
    """Partition dt=D covers [D 00:00, D+1 00:00) UTC; the upper bound is the snapshot end."""
    day = datetime.date.fromisoformat(partition_key)
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC)
    return start, start + datetime.timedelta(days=1)


def latest_is_stale(existing_snapshot_date: str | None, partition_key: str) -> bool:
    """latest/ advances monotonically: a partition at or ahead of what latest/ currently holds
    rewrites it (so delayed retries of the newest day still repair it), while backfills of older
    days never clobber it. ISO date strings compare chronologically."""
    return existing_snapshot_date is None or partition_key >= existing_snapshot_date


def skip_unconfigured(context: dagster.AssetExecutionContext) -> bool:
    if dataset_unconfigured():
        context.log.warning(
            f"{S3_BUCKET_ENV} is not set on this Cloud deployment; skipping until the dedicated bucket is provisioned"
        )
        return True
    return False


# boto3.client("s3") is left untyped on purpose: mypy and pyright resolve it to different stub
# packages (mypy_boto3_s3 vs types_boto3_s3), so a concrete S3Client annotation can't satisfy both.
def s3_client():  # noqa: ANN201
    # The dedicated bucket is reached via ambient AWS config (the node role on prod). Without it,
    # every other environment (local dev, self-hosted, CI) uses the deployment's object-storage
    # service, which needs its explicit endpoint and credentials regardless of DEBUG.
    if settings.INBOX_RANKING_DATASET_S3_BUCKET:
        return boto3.client("s3")
    return boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        region_name=settings.OBJECT_STORAGE_REGION,
    )


SNAPSHOT_DATE_METADATA_KEY = "snapshot-date"


def write_parquet(client, bucket: str, key: str, table: pa.Table, snapshot_date: str | None = None) -> None:
    """Write one Parquet object at a deterministic key.

    Spooled to a temp file and uploaded with `upload_fileobj` rather than held as bytes for
    `put_object`: the embeddings and model-data snapshots carry a 1536-float vector per live report,
    so they grow past both the 5 GB single-request ceiling and what a second in-memory copy of the
    encoded file costs. `upload_fileobj` switches to a multipart upload on its own once the object
    is large enough."""
    metadata = {SNAPSHOT_DATE_METADATA_KEY: snapshot_date} if snapshot_date else {}
    with tempfile.TemporaryFile() as spool:
        pq.write_table(table, spool, compression="zstd")
        spool.seek(0)
        client.upload_fileobj(spool, bucket, key, ExtraArgs={"Metadata": metadata})


def object_snapshot_date(client, bucket: str, key: str) -> str | None:
    """The snapshot-date stamped on an object at write time, or None when the object is missing
    (or predates the stamp), so callers treat it as replaceable."""
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return head.get("Metadata", {}).get(SNAPSHOT_DATE_METADATA_KEY)


def read_parquet(client, bucket: str, key: str) -> pa.Table:
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pq.read_table(pa.BufferReader(body))


def ensure_utc(value: datetime.datetime | None) -> datetime.datetime | None:
    """ClickHouse drivers return naive UTC datetimes; Parquet timestamp columns want aware ones."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value
