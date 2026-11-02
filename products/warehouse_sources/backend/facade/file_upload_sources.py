"""
File upload source wiring for the data_warehouse table API.

The table endpoints use these to turn an uploaded file into a file upload source, to replace the file
a source reads, and to tell whether PostHog may delete an uploaded file. Every function takes the
team id from the caller's request and checks the client-supplied upload id and filename itself, so a
crafted value can't name a file outside the team's folder. These pull the source registry and the
Temporal client, so this module stays off the ``django.setup()`` path.
"""

from uuid import UUID

from posthog.models.team import Team

from products.warehouse_sources.backend import file_upload_sources as _service
from products.warehouse_sources.backend.facade.contracts import (
    FileUploadSourceError,
    UploadedFileRef,
    UploadReadSettings,
)
from products.warehouse_sources.backend.file_uploads import (
    TABLE_FORMAT_TO_FILE_FORMAT,
    InvalidUploadError,
    LegacyUpload,
    UploadLocation,
    is_safe_upload_filename,
    parse_hosted_upload,
    sanitize_upload_filename,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage import (
    delete_upload_if_unused as _delete_upload_if_unused,
    upload_in_use as _upload_in_use,
)

__all__ = [
    "can_replace_file",
    "create_file_upload_source",
    "discard_unused_upload",
    "file_upload_sources_enabled",
    "has_file_upload_source",
    "hosted_upload_in_use",
    "is_legacy_upload_url",
    "is_safe_upload_filename",
    "object_storage_sources_enabled",
    "read_upload_in_place",
    "replace_file_upload",
    "sanitize_upload_filename",
    "upload_format_for_table_format",
]


def file_upload_sources_enabled(team_id: int) -> bool:
    team = Team.objects.only("id", "organization_id").get(pk=team_id)
    return _service.file_upload_sources_enabled(team)


def object_storage_sources_enabled(team_id: int) -> bool:
    """Whether the team has the managed object storage sources, which replace self-managed tables.

    One flag gates every object storage source and the file upload source, so this is the same check.
    """
    return file_upload_sources_enabled(team_id)


def read_upload_in_place(team_id: int, table_name: str, upload: UploadedFileRef) -> UploadReadSettings:
    """Raises `UnreadableUploadError` when ClickHouse can't read the file."""
    return _service.read_upload_in_place(team_id, table_name, _service.UploadedFile.from_ref(team_id, upload))


def create_file_upload_source(
    team_id: int, table_id: UUID, upload: UploadedFileRef, read_settings: UploadReadSettings
) -> None:
    """Give a saved table made from an upload its file upload source, and start the first sync."""
    table = DataWarehouseTable.objects.get(team_id=team_id, pk=table_id)
    _service.create_file_upload_source(table, _service.UploadedFile.from_ref(team_id, upload), read_settings)


def has_file_upload_source(team_id: int, table_id: UUID) -> bool:
    """Whether a file upload source links to the table, so deleting the source deletes the table."""
    table = DataWarehouseTable.objects.filter(team_id=team_id, pk=table_id).first()
    return table is not None and _service.find_file_upload_schema(table) is not None


def can_replace_file(team_id: int, table_id: UUID) -> bool:
    """Whether a new upload for the table goes to a file upload source: one that imports the table, or
    the one the self-managed migration made for it."""
    table = DataWarehouseTable.objects.filter(team_id=team_id, pk=table_id).first()
    return table is not None and _service.find_replaceable_upload_schema(table) is not None


def upload_format_for_table_format(table_format: str) -> str | None:
    """The upload format a file upload source reads a file of this table format in, or None when it can't."""
    return TABLE_FORMAT_TO_FILE_FORMAT.get(table_format)


def replace_file_upload(
    team_id: int, table_id: UUID, upload: UploadedFileRef, read_settings: UploadReadSettings
) -> None:
    """Raises `FileUploadSourceError` when the table has no file upload source or a sync can't start."""
    table = DataWarehouseTable.objects.get(team_id=team_id, pk=table_id)
    schema = _service.find_replaceable_upload_schema(table)
    if schema is None:
        raise FileUploadSourceError("Only a table made from an uploaded file can have its file replaced.")
    _service.replace_file_upload(schema, _service.UploadedFile.from_ref(team_id, upload), read_settings)


def hosted_upload_in_use(team_id: int, url_pattern: str, exclude_table_id: UUID) -> bool:
    """Whether a file upload source, or another table, still reads the team's uploaded file at `url_pattern`."""
    hosted = parse_hosted_upload(team_id, url_pattern)
    return hosted is not None and _upload_in_use(hosted, exclude_table_id=str(exclude_table_id))


def discard_unused_upload(team_id: int, upload: UploadedFileRef) -> None:
    """Best-effort delete of an upload that no source or table reads, such as one a refused replace stored."""
    try:
        location = UploadLocation(team_id=team_id, upload_id=upload.upload_id, filename=upload.filename)
    except InvalidUploadError:
        return
    _delete_upload_if_unused(location)


def is_legacy_upload_url(team_id: int, url_pattern: str) -> bool:
    """Whether `url_pattern` names a file the legacy `file` action stored for the team."""
    return isinstance(parse_hosted_upload(team_id, url_pattern), LegacyUpload)
