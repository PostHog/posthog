"""Storage contract for user-uploaded source files.

Framework-free and source-agnostic on purpose: the upload endpoint and the table-create endpoint
(both in ``data_warehouse``) share this key layout, so it has to live in exactly one place. Uploads
land in PostHog's own data warehouse bucket, namespaced by team then by a per-upload id, which is
what keeps a table's read path scoped to its own team's files.

An uploaded file becomes a self-managed ``DataWarehouseTable`` pointing straight at the stored
object: PostHog reads it in place from its own bucket. A team with the object storage sources also
gets a file upload source that imports the file into a managed table (see ``file_upload_sources``).

Every key is built from a team id that PostHog supplies, never from request input. The parts a
client sends (the upload id and the filename) go through ``UploadLocation`` before they reach a key,
so a crafted value can't name an object outside the team's own folder.
"""

import re
import uuid

from django.conf import settings

from posthog.dataclasses import frozen

# Top-level bucket folder for user-uploaded files.
FILE_UPLOADS_FOLDER = "file_uploads"
# Folder the legacy `file` table action writes to, with one object per team and filename.
LEGACY_UPLOADS_FOLDER = "managed"

_UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^a-zA-Z0-9._-]")
# One key segment that is never '.', '..' or a hidden name.
_SAFE_FILENAME = re.compile(r"[a-zA-Z0-9_-][a-zA-Z0-9._-]*")

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
# The upload format a table of each read format was made from.
TABLE_FORMAT_TO_FILE_FORMAT: dict[str, str] = {
    table_format: file_format for file_format, table_format in FILE_FORMAT_TO_TABLE_FORMAT.items()
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


def sanitize_upload_filename(name: str) -> str | None:
    """The name an uploaded file is stored under, or None when nothing safe is left of it."""
    safe_filename = _UNSAFE_FILENAME_CHARACTERS.sub("_", name)
    return safe_filename if is_safe_upload_filename(safe_filename) else None


def is_safe_upload_filename(filename: object) -> bool:
    return isinstance(filename, str) and _SAFE_FILENAME.fullmatch(filename) is not None


class InvalidUploadError(ValueError):
    """An upload id or a filename that can't name an object in the team's upload folder."""


def _validate_team_id(team_id: object) -> None:
    if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id <= 0:
        raise InvalidUploadError("The upload doesn't belong to a valid team.")


@frozen
class UploadLocation:
    """One uploaded file in PostHog's bucket: `file_uploads/team_<team_id>/<upload_id>/<filename>`."""

    team_id: int
    upload_id: str
    filename: str

    def __post_init__(self) -> None:
        _validate_team_id(self.team_id)
        try:
            canonical_id = str(uuid.UUID(self.upload_id))
        except (TypeError, ValueError, AttributeError):
            canonical_id = None
        # Only the canonical spelling, so one upload has exactly one key.
        if canonical_id is None or canonical_id != self.upload_id:
            raise InvalidUploadError("The upload id isn't valid.")
        if not is_safe_upload_filename(self.filename):
            raise InvalidUploadError("The uploaded filename isn't valid.")

    @property
    def folder_key(self) -> str:
        return build_file_upload_s3_prefix(self.team_id, self.upload_id)

    @property
    def key(self) -> str:
        return f"{self.folder_key}/{self.filename}"

    @property
    def path(self) -> str:
        """``bucket/key``, the form s3fs takes."""
        return f"{settings.DATAWAREHOUSE_BUCKET}/{self.key}"

    @property
    def url_pattern(self) -> str:
        return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{self.key}"


@frozen
class LegacyUpload:
    """A file the legacy `file` table action stored: `managed/team_<team_id>/<filename>`."""

    team_id: int
    filename: str

    def __post_init__(self) -> None:
        _validate_team_id(self.team_id)
        if not is_safe_upload_filename(self.filename):
            raise InvalidUploadError("The uploaded filename isn't valid.")

    @property
    def key(self) -> str:
        return f"{LEGACY_UPLOADS_FOLDER}/team_{self.team_id}/{self.filename}"

    @property
    def path(self) -> str:
        return f"{settings.DATAWAREHOUSE_BUCKET}/{self.key}"

    @property
    def url_pattern(self) -> str:
        return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{self.key}"


HostedUpload = UploadLocation | LegacyUpload


def parse_hosted_upload(team_id: int, url_pattern: str) -> HostedUpload | None:
    """The uploaded file one of `team_id`'s tables reads, or None when its URL names anything else.

    Exact on purpose: other objects in PostHog's bucket (synced tables, materialized views) and other
    teams' uploads give None, so a caller that copies or deletes the result only ever touches a file
    this team uploaded.
    """
    domain = settings.DATAWAREHOUSE_BUCKET_DOMAIN
    if not domain or not settings.DATAWAREHOUSE_BUCKET:
        return None
    prefix = f"https://{domain}/"
    if not url_pattern.startswith(prefix):
        return None
    segments = url_pattern[len(prefix) :].split("/")
    team_folder = f"team_{team_id}"
    try:
        if len(segments) == 4 and segments[:2] == [FILE_UPLOADS_FOLDER, team_folder]:
            return UploadLocation(team_id=team_id, upload_id=segments[2], filename=segments[3])
        if len(segments) == 3 and segments[:2] == [LEGACY_UPLOADS_FOLDER, team_folder]:
            return LegacyUpload(team_id=team_id, filename=segments[2])
    except InvalidUploadError:
        return None
    return None
