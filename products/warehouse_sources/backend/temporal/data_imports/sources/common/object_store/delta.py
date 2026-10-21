import re
import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import ClassVar, cast

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable
from deltalake.exceptions import DeltaError, DeltaProtocolError, TableNotFoundError
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ACCESS_DENIED_ERROR,
    DELTA_UNSUPPORTED_ERROR,
    FILE_PARSE_ERROR,
    NO_TABLE_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    DELTA_BATCH_ROWS,
)

# Whole words only, so a status code doesn't match inside an object key such as `sales403/part.parquet`.
_ACCESS_DENIED_MARKERS = re.compile(r"\b(403|AccessDenied|Forbidden|InvalidAccessKeyId|SignatureDoesNotMatch)\b")


def _raise_if_access_denied(error: Exception, table_name: str) -> None:
    # delta-rs reports object store failures as text, so a rejected credential shows only as the
    # HTTP status or the S3 error code inside the message.
    if _ACCESS_DENIED_MARKERS.search(str(error)):
        raise ObjectStorageError(
            f"{ACCESS_DENIED_ERROR} for the Delta table '{table_name}'. Check that the key can read its folder."
        ) from error


# The table version a row was imported at. An append-only sync needs a column for the pipeline's
# incremental field, and the version is the one value that grows with every sync.
DELTA_VERSION_COLUMN = "_delta_version"


@frozen
class ObjectStorageDeltaCursor:
    """The Delta table version the destination holds."""

    cursor_kind: ClassVar[str] = "object_storage_delta_v1"

    version: int
    # Delta gives a table a new ID when it is dropped and created again, which restarts its versions.
    table_id: str


@contextmanager
def _delta_errors(table_name: str) -> Iterator[None]:
    try:
        yield
    except DeltaProtocolError as e:
        raise ObjectStorageError(f"{DELTA_UNSUPPORTED_ERROR}: {e}") from e
    except TableNotFoundError as e:
        raise ObjectStorageError(
            f"{NO_TABLE_FILES_ERROR} '{table_name}'. The Delta table is no longer at its folder in the bucket."
        ) from e
    except (DeltaError, OSError) as e:
        _raise_if_access_denied(e, table_name)
        raise


@frozen
class DeltaRead:
    """One planned read of a Delta table.

    The version is pinned when the plan is made, so commits that land during the read don't mix two
    versions into one import.
    """

    table_name: str
    dataset: ds.FileSystemDataset = dataclasses.field(repr=False)
    # What the destination holds once this read is written.
    cursor: ObjectStorageDeltaCursor
    # The data files to read. None means the whole snapshot.
    added_files: tuple[ds.FileFragment, ...] | None = dataclasses.field(default=None, repr=False)
    # The stored cursor can't be extended by appending, so the destination must be rebuilt.
    reset_required: bool = False

    def iter_tables(self, batch_rows: int = DELTA_BATCH_ROWS, with_version: bool = False) -> Iterator[pa.Table]:
        """Stream the planned rows. The scan reads one fragment at a time on one thread to bound memory."""
        dataset: ds.Dataset = self.dataset
        if self.added_files is not None:
            if not self.added_files:
                return
            # Built from the snapshot's own fragments, so partition columns come back as in a full read.
            dataset = ds.FileSystemDataset(
                list(self.added_files), self.dataset.schema, self.dataset.format, self.dataset.filesystem
            )
        scanner = dataset.scanner(batch_size=batch_rows, batch_readahead=1, fragment_readahead=1, use_threads=False)
        yielded = False
        try:
            for batch in scanner.to_batches():
                if batch.num_rows:
                    yielded = True
                    yield self._with_version(pa.Table.from_batches([batch]), with_version)
        except pa.ArrowInvalid as e:
            raise ObjectStorageError(
                f"{FILE_PARSE_ERROR} a data file of the Delta table '{self.table_name}': {e}"
            ) from e
        except (DeltaError, OSError) as e:
            # The scan reads the data files lazily, so a key that can read the log but not the data fails here.
            _raise_if_access_denied(e, self.table_name)
            raise
        if not yielded and self.added_files is None:
            # An empty snapshot still has to reach the pipeline as a schema, or the table is dropped and
            # never recreated.
            yield self._with_version(self.dataset.schema.empty_table(), with_version)

    def _with_version(self, table: pa.Table, with_version: bool) -> pa.Table:
        if not with_version:
            return table
        if DELTA_VERSION_COLUMN in table.column_names:
            table = table.drop_columns([DELTA_VERSION_COLUMN])
        return table.append_column(
            DELTA_VERSION_COLUMN, pa.repeat(pa.scalar(self.cursor.version, pa.int64()), table.num_rows)
        )


def _files_at_version(uri: str, storage_options: dict[str, str], version: int) -> set[str] | None:
    """The data files of an earlier version, or None when that version can no longer be read."""
    try:
        dataset = DeltaTable(uri, version=version, storage_options=storage_options).to_pyarrow_dataset()
    except DeltaError:
        # delta-rs reports a version whose log entries were cleaned up as a `DeltaError`. Object store
        # failures such as timeouts, throttling or outages come as `OSError` and propagate, so the sync
        # retries instead of rebuilding the whole table.
        return None
    return {fragment.path for fragment in dataset.get_fragments()}


def plan_delta_read(
    uri: str,
    storage_options: dict[str, str],
    table_name: str,
    stored: ObjectStorageDeltaCursor | None = None,
    logger: FilteringBoundLogger | None = None,
) -> DeltaRead:
    """Pin the table's current version and decide what to read to bring the destination up to it.

    Without a stored cursor the whole snapshot is read. With one, only the data files added since
    the cursor's version are read, and only when every file of that version is still in the table.
    A file that is gone was removed by a delete, an update, a merge, an overwrite or a compaction,
    all of which change or move rows the destination already holds. No append can repair that, so
    the plan then asks for a rebuild from the whole snapshot.
    """
    with _delta_errors(table_name):
        table = DeltaTable(uri, storage_options=storage_options)
        cursor = ObjectStorageDeltaCursor(version=table.version(), table_id=str(table.metadata().id))
        dataset = cast(ds.FileSystemDataset, table.to_pyarrow_dataset())

    if logger is not None:
        logger.info("Reading Delta table snapshot", table=table_name, delta_version=cursor.version)
    if stored is None:
        return DeltaRead(table_name=table_name, dataset=dataset, cursor=cursor)
    if stored.table_id == cursor.table_id and stored.version == cursor.version:
        return DeltaRead(table_name=table_name, dataset=dataset, cursor=cursor, added_files=())

    reset_reason: str | None = None
    added_files: list[ds.FileFragment] = []
    if stored.table_id != cursor.table_id:
        reset_reason = "the table was created again"
    elif stored.version > cursor.version:
        reset_reason = "the table is at an earlier version than the last sync"
    else:
        with _delta_errors(table_name):
            earlier_files = _files_at_version(uri, storage_options, stored.version)
        fragments: list[ds.FileFragment] = list(dataset.get_fragments())
        if earlier_files is None:
            reset_reason = "the version of the last sync can no longer be read"
        elif not earlier_files <= {fragment.path for fragment in fragments}:
            reset_reason = "a commit since the last sync removed or rewrote data files"
        else:
            added_files = [fragment for fragment in fragments if fragment.path not in earlier_files]

    if reset_reason is not None:
        if logger is not None:
            logger.warning(
                "Rebuilding the Delta table import from the whole snapshot",
                table=table_name,
                reason=reset_reason,
                stored_version=stored.version,
                delta_version=cursor.version,
            )
        return DeltaRead(table_name=table_name, dataset=dataset, cursor=cursor, reset_required=True)
    return DeltaRead(table_name=table_name, dataset=dataset, cursor=cursor, added_files=tuple(added_files))


def iter_delta_tables(
    uri: str,
    storage_options: dict[str, str],
    table_name: str,
    batch_rows: int = DELTA_BATCH_ROWS,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[pa.Table]:
    """Stream one whole Delta snapshot."""
    yield from plan_delta_read(uri, storage_options, table_name, logger=logger).iter_tables(batch_rows)
