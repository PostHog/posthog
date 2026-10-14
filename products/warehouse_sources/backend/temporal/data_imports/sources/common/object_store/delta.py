import re
from collections.abc import Iterator

import pyarrow as pa
from deltalake import DeltaTable
from deltalake.exceptions import DeltaError, DeltaProtocolError, TableNotFoundError
from structlog.types import FilteringBoundLogger

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


def iter_delta_tables(
    uri: str,
    storage_options: dict[str, str],
    table_name: str,
    batch_rows: int = DELTA_BATCH_ROWS,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[pa.Table]:
    """Stream one Delta snapshot.

    The version is pinned when the table opens, so commits that land during the read don't mix two
    versions into one import. The scan reads one fragment at a time on one thread to bound memory.
    """
    try:
        table = DeltaTable(uri, storage_options=storage_options)
        version = table.version()
        dataset = table.to_pyarrow_dataset()
    except DeltaProtocolError as e:
        raise ObjectStorageError(f"{DELTA_UNSUPPORTED_ERROR}: {e}") from e
    except TableNotFoundError as e:
        raise ObjectStorageError(
            f"{NO_TABLE_FILES_ERROR} '{table_name}'. The Delta table is no longer at its folder in the bucket."
        ) from e
    except (DeltaError, OSError) as e:
        _raise_if_access_denied(e, table_name)
        raise

    if logger is not None:
        logger.info("Reading Delta table snapshot", table=table_name, delta_version=version)

    scanner = dataset.scanner(batch_size=batch_rows, batch_readahead=1, fragment_readahead=1, use_threads=False)
    yielded = False
    try:
        for batch in scanner.to_batches():
            if batch.num_rows:
                yielded = True
                yield pa.Table.from_batches([batch])
    except pa.ArrowInvalid as e:
        raise ObjectStorageError(f"{FILE_PARSE_ERROR} a data file of the Delta table '{table_name}': {e}") from e
    except (DeltaError, OSError) as e:
        # The scan reads the data files lazily, so a key that can read the log but not the data fails here.
        _raise_if_access_denied(e, table_name)
        raise
    if not yielded:
        # An empty snapshot still has to reach the pipeline as a schema, or the table is dropped and
        # never recreated.
        yield dataset.schema.empty_table()
