"""Storage contract for user-uploaded source files.

Framework-free and source-agnostic on purpose: the upload endpoint and the table-create endpoint
(both in ``data_warehouse``) share this key layout, so it has to live in exactly one place. Uploads
land in PostHog's own data warehouse bucket, namespaced by team then by a per-upload id, which is
what keeps a table's read path scoped to its own team's files.

An uploaded file becomes a self-managed ``DataWarehouseTable`` pointing straight at the stored
object: PostHog reads it in place from its own bucket, so there is no import pipeline and no
recurring sync — the same shape as a linked S3/GCS bucket, just hosted by us.
"""

from django.conf import settings

# Top-level bucket folder for user-uploaded files.
FILE_UPLOADS_FOLDER = "file_uploads"

# Formats a user can upload. Lowercase tokens accepted by the upload endpoint and mapped to a
# ClickHouse read format (`FILE_FORMAT_TO_TABLE_FORMAT`) when the table is created.
FORMAT_CSV = "csv"
FORMAT_JSON = "json"
FORMAT_PARQUET = "parquet"

SUPPORTED_FILE_FORMATS = (FORMAT_CSV, FORMAT_JSON, FORMAT_PARQUET)

# Maps an uploaded file's format to the `DataWarehouseTable.TableFormat` value ClickHouse reads it
# with in place. CSV is assumed to carry a header row (the common export shape), and JSON is read as
# newline-delimited rows — the same format a self-managed S3 JSON table uses. Kept as plain strings
# so this module stays free of the model import.
FILE_FORMAT_TO_TABLE_FORMAT: dict[str, str] = {
    FORMAT_CSV: "CSVWithNames",
    FORMAT_JSON: "JSONEachRow",
    FORMAT_PARQUET: "Parquet",
}

# Cap on uploads streamed through the web pod. Larger datasets belong on a self-managed S3/GCS
# source, where PostHog reads the customer's bucket directly instead of hosting the bytes.
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024


def build_file_upload_s3_prefix(team_id: int, upload_id: str) -> str:
    """Folder holding one upload's object, keyed by team then upload id."""
    return f"{FILE_UPLOADS_FOLDER}/team_{team_id}/{upload_id}"


def build_file_upload_s3_key(team_id: int, upload_id: str, filename: str) -> str:
    """Bucket-relative S3 key for one uploaded file."""
    return f"{build_file_upload_s3_prefix(team_id, upload_id)}/{filename}"


def build_file_upload_s3_path(team_id: int, upload_id: str, filename: str) -> str:
    """Bucket-qualified ``bucket/key`` path, the form s3fs takes. Use this for every read and write
    of an uploaded file so the upload endpoint and the import pipeline can't drift apart."""
    return f"{settings.DATAWAREHOUSE_BUCKET}/{build_file_upload_s3_key(team_id, upload_id, filename)}"


def build_file_upload_s3_uri(team_id: int, upload_id: str, filename: str) -> str:
    """Full ``s3://`` URI into the data warehouse bucket for one uploaded file."""
    return f"s3://{build_file_upload_s3_path(team_id, upload_id, filename)}"


def build_file_upload_url_pattern(team_id: int, upload_id: str, filename: str) -> str:
    """``https://`` URL used as the self-managed table's ``url_pattern``.

    This is the form `DataWarehouseTable.get_columns` builds its ClickHouse s3 table function from.
    The object lives in PostHog's own bucket, so the table carries no credential and reads fall back
    to the node role — never a user-supplied key. Built server-side from the source's own team, so a
    client-supplied ``upload_id`` can only ever resolve inside that team's folder.
    """
    return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{build_file_upload_s3_key(team_id, upload_id, filename)}"


def hosted_upload_s3_path(url_pattern: str) -> str | None:
    """The bucket-qualified ``bucket/key`` path (the form s3fs takes) backing a self-managed table
    whose file PostHog hosts in its own data warehouse bucket, or ``None`` when the table reads from
    anywhere else — most importantly a customer-linked S3/GCS bucket, which is never ours to delete.

    The gate is the URL host: only ``url_pattern``s under ``DATAWAREHOUSE_BUCKET_DOMAIN`` are hosted
    by us. That covers both the current ``file_uploads/`` prefix and the legacy ``managed/`` one.
    """
    domain = settings.DATAWAREHOUSE_BUCKET_DOMAIN
    bucket = settings.DATAWAREHOUSE_BUCKET
    if not domain or not bucket:
        return None
    prefix = f"https://{domain}/"
    if not url_pattern.startswith(prefix):
        return None
    key = url_pattern[len(prefix) :]
    if not key:
        return None
    return f"{bucket}/{key}"
