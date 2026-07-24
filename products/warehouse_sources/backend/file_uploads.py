"""Storage contract for user-uploaded source files.

Framework-free and source-agnostic on purpose: the upload endpoint and the table-create endpoint
(both in ``data_warehouse``) share this key layout, so it has to live in exactly one place. Uploads
land in PostHog's own data warehouse bucket, namespaced by team then by a per-upload id, which is
what keeps a table's read path scoped to its own team's files.

An uploaded file becomes a self-managed ``DataWarehouseTable`` pointing straight at the stored
object: PostHog reads it in place from its own bucket, so there is no import pipeline and no
recurring sync — the same shape as a linked S3/GCS bucket, just hosted by us.
"""

import os

from django.conf import settings

# Top-level bucket folder for user-uploaded files.
FILE_UPLOADS_FOLDER = "file_uploads"

# Formats a user can upload. Lowercase tokens accepted by the upload endpoint and mapped to a
# ClickHouse read format (`FILE_FORMAT_TO_TABLE_FORMAT`) when the table is created.
FORMAT_CSV = "csv"
FORMAT_JSON = "json"
FORMAT_PARQUET = "parquet"

# Excel is an upload-only input format, never a stored/read format: ClickHouse has no Excel reader,
# so the upload endpoint converts the workbook to Parquet before storing it. It therefore appears in
# UPLOAD_ACCEPTED_FORMATS (what a client may send) but not in SUPPORTED_FILE_FORMATS (what a table is
# built from) — by the time create_from_upload runs, the object is already Parquet.
FORMAT_XLSX = "xlsx"

SUPPORTED_FILE_FORMATS = (FORMAT_CSV, FORMAT_JSON, FORMAT_PARQUET)

# Formats the upload endpoint accepts as input. Superset of SUPPORTED_FILE_FORMATS because Excel is
# converted to Parquet on the way in rather than read in place.
UPLOAD_ACCEPTED_FORMATS = (*SUPPORTED_FILE_FORMATS, FORMAT_XLSX)

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


class ExcelConversionError(Exception):
    """An uploaded Excel workbook couldn't be turned into a Parquet table. The message is safe to
    surface to the user (it names what to fix), so the upload endpoint maps it straight to a 400."""


def excel_stored_filename(original_filename: str) -> str:
    """Name the converted Parquet object is stored under, derived from the uploaded workbook's name
    (``sales.xlsx`` -> ``sales.parquet``). The stored object is Parquet, so the name must match."""
    stem = os.path.splitext(original_filename)[0] or "upload"
    return f"{stem}.parquet"


def excel_to_parquet_bytes(data: bytes) -> bytes:
    """Convert an ``.xlsx``/``.xlsm`` workbook's first sheet to Parquet bytes.

    ClickHouse can't read Excel, so a self-managed table can't point at the workbook directly. We
    read the first sheet into a dataframe and re-encode it as Parquet, which ClickHouse reads
    natively and which preserves column types better than a CSV round-trip. Only the first sheet is
    converted — a workbook maps to one table, matching the one-file-one-table upload contract.

    pandas/openpyxl/pyarrow are heavy and only needed on this path, so they're imported lazily to
    keep them off the module (and Django startup) import path.
    """
    import io  # noqa: PLC0415 — keep the heavy Excel/Parquet stack off the import path

    import pandas as pd  # noqa: PLC0415

    try:
        # engine pinned to openpyxl: it reads .xlsx/.xlsm only, so a mis-typed .xls (which needs the
        # separate xlrd engine we don't ship) fails here with a clear error rather than silently.
        frame = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl")
    except Exception as error:
        raise ExcelConversionError(
            "Could not read the Excel file. Make sure it's a valid .xlsx or .xlsm workbook."
        ) from error

    if frame.shape[1] == 0:
        raise ExcelConversionError("The first sheet has no columns. Add a header row and try again.")

    buffer = io.BytesIO()
    frame.to_parquet(buffer, engine="pyarrow", index=False)
    return buffer.getvalue()
