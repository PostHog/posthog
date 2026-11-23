"""
File upload source wiring for the data_warehouse table API.

The table endpoints use these to turn an uploaded file into a file upload source, to replace the file
a source reads, and to tell whether PostHog may delete an uploaded file. Every function takes the
team id from the caller's request and checks the client-supplied upload id and filename itself, so a
crafted value can't name a file outside the team's folder. These pull the source registry and the
Temporal client, so this module stays off the ``django.setup()`` path.
"""

from uuid import UUID

from products.warehouse_sources.backend import file_upload_sources as _service
from products.warehouse_sources.backend.facade.contracts import (
    FileUploadSourceError,
    UploadedFileRef,
    UploadReadSettings,
)
from products.warehouse_sources.backend.file_uploads import (
    is_safe_upload_filename,
    parse_hosted_upload,
    sanitize_upload_filename,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage import (
    upload_in_use as _upload_in_use,
)

__all__ = [
    "can_replace_file",
    "create_file_upload_source",
    "has_file_upload_source",
    "hosted_upload_in_use",
    "is_safe_upload_filename",
    "read_upload_in_place",
    "replace_file_upload",
    "sanitize_upload_filename",
]


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
