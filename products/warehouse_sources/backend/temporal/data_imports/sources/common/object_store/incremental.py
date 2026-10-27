import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import FILE_PATH_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import StoredObject
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    APPEND_SETTLE_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ReplaceScope, SourceInputs
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType

FILE_ROW_NUMBER_COLUMN = "_file_row_number"
# A rewritten file replaces its own rows, because a row keeps its position in the file.
FILE_PRIMARY_KEYS = [FILE_PATH_COLUMN, FILE_ROW_NUMBER_COLUMN]

# `all` reads every file. `changed` reads the files at or after the watermark and merges them.
# `new` reads only the files after the watermark and appends them.
SelectionMode = Literal["all", "changed", "new"]


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@frozen
class FileSelection:
    """Which of a table's files one sync reads, decided by the files' modification times."""

    mode: SelectionMode = "all"
    watermark: datetime | None = None

    @classmethod
    def from_inputs(cls, inputs: SourceInputs) -> "FileSelection":
        if not inputs.should_use_incremental_field:
            return cls()
        mode: SelectionMode = "new" if inputs.sync_type == ExternalDataSchemaSyncType.APPEND else "changed"
        return cls(mode=mode, watermark=_as_utc(inputs.db_incremental_field_last_value))

    @property
    def merges(self) -> bool:
        return self.mode == "changed"

    def select(self, files: Iterable[StoredObject], now: datetime | None = None) -> list[StoredObject]:
        if self.mode == "all":
            return list(files)
        selected = list(files)
        if self.mode == "new":
            # An append has no key to dedupe on, so the boundary is exclusive: reading the watermark's
            # files again would add their rows twice. A file that lands later with the same timestamp
            # as the watermark would then be skipped for good. To prevent that, a file is left for
            # the next sync until its timestamp is old enough that no other file can still take it.
            # The cost is that a file is imported one sync late when it lands right before a sync.
            settled_before = (now or datetime.now(UTC)) - timedelta(seconds=APPEND_SETTLE_SECONDS)
            selected = [stored for stored in selected if stored.modified_at <= settled_before]
            if self.watermark is not None:
                selected = [stored for stored in selected if stored.modified_at > self.watermark]
        elif self.watermark is not None:
            # Inclusive, because the merge dedupes the rows of a file that is read again.
            selected = [stored for stored in selected if stored.modified_at >= self.watermark]
        # Oldest first, so the watermark the pipeline takes from the rows only moves forward.
        return sorted(selected, key=lambda stored: (stored.modified_at, stored.path))


READ_ALL = FileSelection()


def listing_digest(files: Iterable[StoredObject]) -> str:
    """A 64-character digest of the path, size and modification time of each file."""
    digest = hashlib.sha256()
    for stored in sorted(files, key=lambda stored: stored.path):
        digest.update(f"{stored.path}\t{stored.size}\t{stored.modified_at.isoformat()}\n".encode())
    return digest.hexdigest()


@frozen
class MirrorPlan:
    """One incremental read that makes a files table match the bucket.

    The changed files are read again and replace their own rows, and the rows of a file that is no
    longer in the bucket go (see `ReplaceScope`).
    """

    files: list[StoredObject]
    """The files to read, oldest first."""
    replace_scope: ReplaceScope | None
    """None when nothing changed since the last sync, so the run reads and deletes nothing."""
    digest: str
    """The digest of the listing that this read brings the table up to."""


def plan_mirror(
    listed: Sequence[StoredObject], selection: FileSelection, stored_digest: str | None, now: datetime | None = None
) -> MirrorPlan:
    """Plan the read from the current listing and the digest of the listing at the last sync."""
    digest = listing_digest(listed)
    if digest == stored_digest:
        # The files at the watermark are read again on every run, so the watermark alone can never
        # tell that a listing has not changed.
        return MirrorPlan(files=[], replace_scope=None, digest=digest)
    files = selection.select(listed, now=now)
    scope = ReplaceScope(
        column=FILE_PATH_COLUMN,
        replaced=frozenset(stored.path for stored in files),
        retained=frozenset(stored.path for stored in listed),
    )
    return MirrorPlan(files=files, replace_scope=scope, digest=digest)
