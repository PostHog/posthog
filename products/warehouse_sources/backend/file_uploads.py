"""Storage contract for user-uploaded source files.

Framework-free and source-agnostic on purpose: the upload endpoint and the table-create endpoint
(both in ``data_warehouse``) share this key layout, so it has to live in exactly one place. Uploads
land in PostHog's own data warehouse bucket, namespaced by team then by a per-upload id, which is
what keeps a table's read path scoped to its own team's files.

An uploaded file becomes a self-managed ``DataWarehouseTable`` pointing straight at the stored
object: PostHog reads it in place from its own bucket, so there is no import pipeline and no
recurring sync — the same shape as a linked S3/GCS bucket, just hosted by us.
"""

import re

from django.conf import settings

# Top-level bucket folder for user-uploaded files.
FILE_UPLOADS_FOLDER = "file_uploads"

# Cap on the stored filename. It is concatenated straight into an S3 object key, and an over-long
# or malformed key makes S3 reject HeadObject with a 400 rather than answering a clean 404. 255
# keeps the whole key comfortably under S3's 1024-byte key limit and matches the common filesystem
# filename length, so it never rejects a name a user could plausibly have uploaded.
MAX_UPLOAD_FILENAME_LENGTH = 255

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

# Per-format guidance shown when column detection fails on create. Each hint names the exact shape
# the matching read format above expects, since that's what silently trips uploads up: CSV needs a
# header row, and JSON is read one object per line rather than as a single array.
FILE_FORMAT_READ_HINTS: dict[str, str] = {
    FORMAT_CSV: "Make sure it's a comma-separated CSV with a header row and the same number of columns in every row.",
    FORMAT_JSON: "Make sure it's newline-delimited JSON, with one object per line rather than a single array.",
    FORMAT_PARQUET: "Make sure it's a valid Parquet file.",
}

# Cap on uploads streamed through the web pod. Larger datasets belong on a self-managed S3/GCS
# source, where PostHog reads the customer's bucket directly instead of hosting the bytes.
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024


def sanitize_upload_filename(filename: str | None) -> str:
    """Reduce a client-supplied filename to a safe S3 object-key segment, or raise ``ValueError``.

    Django already strips path separators via ``os.path.basename`` in ``UploadedFile._set_name``;
    restricting further to a safe character set and a length cap is defense-in-depth for the S3 key.
    Shared by the upload endpoint and the table-create endpoint so the two can't drift on what a
    stored filename may contain — a name that survives here can only ever miss as a clean 404, never
    a malformed-key 400. Rejects an empty result, a leading dot (hidden/relative names), and anything
    past the length cap.
    """
    safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename or "")
    if not safe_filename or safe_filename.startswith("."):
        raise ValueError("Invalid filename")
    if len(safe_filename) > MAX_UPLOAD_FILENAME_LENGTH:
        raise ValueError(f"Filename must be at most {MAX_UPLOAD_FILENAME_LENGTH} characters.")
    return safe_filename


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
