"""The uploaded files a file upload source reads, and when PostHog deletes them.

A source reads one file, named by server-managed `job_inputs`. Replacing the file points the source at
a new upload and records the old one as superseded. The old file stays until a sync that started after
the replacement completes, so a failed sync of the new file still has the old one to fall back on.
Deleting the source deletes its files. A file is only deleted when no other live source or table of
the team still reads it, because one upload can back more than one table.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast

from django.conf import settings
from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.file_uploads import (
    HostedUpload,
    InvalidUploadError,
    LegacyUpload,
    UploadLocation,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

# The `connection_metadata` key that holds the uploads a source no longer reads.
FILE_UPLOAD_METADATA_KEY = "file_upload"
SUPERSEDED_KEY = "superseded"


@frozen
class SupersededUpload:
    upload: HostedUpload
    superseded_at: datetime

    def to_dict(self) -> dict[str, str]:
        if isinstance(self.upload, LegacyUpload):
            return {"legacy_filename": self.upload.filename, "superseded_at": self.superseded_at.isoformat()}
        return {
            "upload_id": self.upload.upload_id,
            "filename": self.upload.filename,
            "superseded_at": self.superseded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, team_id: int, raw: object) -> "SupersededUpload | None":
        """The entry, or None when it can't name an upload of the team, which is then never deleted."""
        if not isinstance(raw, Mapping):
            return None
        try:
            superseded_at = datetime.fromisoformat(str(raw.get("superseded_at")))
            upload: HostedUpload
            if "legacy_filename" in raw:
                upload = LegacyUpload(team_id=team_id, filename=raw["legacy_filename"])
            else:
                # A missing or non-string value fails validation, so the entry is dropped.
                upload = UploadLocation(
                    team_id=team_id, upload_id=cast(str, raw.get("upload_id")), filename=cast(str, raw.get("filename"))
                )
        except (InvalidUploadError, TypeError, ValueError):
            return None
        return cls(upload=upload, superseded_at=superseded_at)


def upload_from_job_inputs(team_id: int, job_inputs: Mapping[str, Any] | None) -> UploadLocation:
    """The file a source reads. The team comes from the source row, never from the inputs."""
    inputs = job_inputs or {}
    return UploadLocation(
        team_id=team_id, upload_id=cast(str, inputs.get("upload_id")), filename=cast(str, inputs.get("filename"))
    )


def superseded_uploads(source: ExternalDataSource) -> list[SupersededUpload]:
    metadata = (source.connection_metadata or {}).get(FILE_UPLOAD_METADATA_KEY)
    entries = metadata.get(SUPERSEDED_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(entries, list):
        return []
    parsed = (SupersededUpload.from_dict(source.team_id, entry) for entry in entries)
    return [entry for entry in parsed if entry is not None]


def _with_superseded(connection_metadata: object, entries: Iterable[SupersededUpload]) -> dict[str, Any]:
    metadata = dict(connection_metadata) if isinstance(connection_metadata, Mapping) else {}
    section = metadata.get(FILE_UPLOAD_METADATA_KEY)
    section = dict(section) if isinstance(section, Mapping) else {}
    section[SUPERSEDED_KEY] = [entry.to_dict() for entry in entries]
    metadata[FILE_UPLOAD_METADATA_KEY] = section
    return metadata


def superseded_metadata(*entries: SupersededUpload) -> dict[str, Any]:
    """`connection_metadata` keys for a new source that starts with superseded uploads."""
    return _with_superseded({}, entries)


def connection_metadata_with_superseded(source: ExternalDataSource, entry: SupersededUpload) -> dict[str, Any]:
    """The source's `connection_metadata` with one more superseded upload. The caller holds the row lock."""
    return _with_superseded(source.connection_metadata, [*superseded_uploads(source), entry])


def upload_in_use(
    upload: HostedUpload, exclude_source_id: str | None = None, exclude_table_id: str | None = None
) -> bool:
    """Whether another live source, or a table that reads the file in place, still needs the upload."""
    readers = DataWarehouseTable.objects.filter(
        team_id=upload.team_id,
        url_pattern=upload.url_pattern,
        credential__isnull=True,
        external_data_source__isnull=True,
        deleted=False,
    )
    if exclude_table_id is not None:
        readers = readers.exclude(pk=exclude_table_id)
    if readers.exists():
        return True
    sources = ExternalDataSource.objects.filter(
        team_id=upload.team_id, source_type=ExternalDataSourceType.FILEUPLOAD, deleted=False
    )
    if exclude_source_id is not None:
        sources = sources.exclude(pk=exclude_source_id)
    # `job_inputs` is encrypted, so the comparison runs here rather than in the query.
    for other in sources.select_related(None).only("id", "team_id", "job_inputs", "connection_metadata"):
        try:
            if upload_from_job_inputs(other.team_id, other.job_inputs) == upload:
                return True
        except InvalidUploadError:
            pass
        # A file another source superseded is that source's to delete once its sync completes.
        if any(entry.upload == upload for entry in superseded_uploads(other)):
            return True
    return False


def _delete_if_unused(upload: HostedUpload, exclude_source_id: str | None) -> bool | None:
    """True when the object was deleted, False when it was kept or already gone, None when storage failed."""
    if not settings.DATAWAREHOUSE_BUCKET or upload_in_use(upload, exclude_source_id):
        return False
    try:
        get_s3_client().rm(upload.path)
    except FileNotFoundError:
        return False
    except Exception as e:
        capture_exception(e)
        logger.warning("Could not delete an uploaded file", team_id=upload.team_id, key=upload.key)
        return None
    return True


def delete_upload_if_unused(upload: HostedUpload, exclude_source_id: str | None = None) -> bool:
    """Best-effort delete. Returns whether the object was deleted."""
    return _delete_if_unused(upload, exclude_source_id) is True


def lock_source(source_id: str, team_id: int) -> ExternalDataSource | None:
    """The source row under a lock. Call inside a transaction."""
    return (
        ExternalDataSource.objects.select_related(None)
        .select_for_update()
        .filter(pk=source_id, team_id=team_id, deleted=False)
        .first()
    )


def release_superseded_uploads(source_id: str, team_id: int, sync_started_at: datetime) -> list[HostedUpload]:
    """Delete the uploads that were superseded before a sync that has now completed started.

    That sync read the source's newer file, so the table no longer depends on the older ones. An
    upload superseded later stays for the sync that reads its replacement, and so does the upload the
    source reads now, in case a replacement pointed it back at an older file. An upload that storage
    fails to delete stays recorded, so the next completed sync tries again.
    """
    with transaction.atomic():
        source = lock_source(source_id, team_id)
        if source is None:
            return []
        entries = superseded_uploads(source)
        due = [entry for entry in entries if entry.superseded_at <= sync_started_at]
        if not due:
            return []
        try:
            current: UploadLocation | None = upload_from_job_inputs(source.team_id, source.job_inputs)
        except InvalidUploadError:
            current = None
        source.connection_metadata = _with_superseded(
            source.connection_metadata, [entry for entry in entries if entry not in due]
        )
        source.save(update_fields=["connection_metadata", "updated_at"])

    deleted: list[HostedUpload] = []
    failed: list[SupersededUpload] = []
    for entry in due:
        if entry.upload == current:
            continue
        result = _delete_if_unused(entry.upload, exclude_source_id=source_id)
        if result is None:
            failed.append(entry)
        elif result:
            deleted.append(entry.upload)
    if failed:
        with transaction.atomic():
            source = lock_source(source_id, team_id)
            if source is not None:
                source.connection_metadata = _with_superseded(
                    source.connection_metadata, [*superseded_uploads(source), *failed]
                )
                source.save(update_fields=["connection_metadata", "updated_at"])
    return deleted


def delete_source_uploads(source: ExternalDataSource) -> list[HostedUpload]:
    """Delete the files of a deleted source that nothing else reads."""
    uploads: list[HostedUpload] = [entry.upload for entry in superseded_uploads(source)]
    try:
        uploads.insert(0, upload_from_job_inputs(source.team_id, source.job_inputs))
    except InvalidUploadError:
        pass
    deleted: list[HostedUpload] = []
    for upload in dict.fromkeys(uploads):
        if delete_upload_if_unused(upload, exclude_source_id=str(source.pk)):
            deleted.append(upload)
    return deleted
