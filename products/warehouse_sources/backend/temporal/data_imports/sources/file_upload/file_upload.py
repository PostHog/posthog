from __future__ import annotations

import io
from collections.abc import AsyncGenerator, Iterator

import orjson
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.settings import (
    FORMAT_CSV,
    FORMAT_JSON,
    FORMAT_PARQUET,
    build_file_upload_s3_path,
)

# Yield rows to the pipeline in bounded chunks so a large uploaded file doesn't materialise one
# oversized Arrow table on the way to the Delta write. Matches the pipeline's default chunk size.
_BATCH_ROWS = 5000

# The 50MB upload cap only bounds the stored object. A highly compressed Parquet file can decompress
# to far more, so cap the decoded size and reject anything larger before materialising it, rather than
# letting a small upload exhaust a shared import worker's memory. Substring is matched in
# `FileUploadSource.get_non_retryable_errors` so a breach fails the sync permanently instead of
# retrying forever.
MAX_DECODED_BYTES = 1024 * 1024 * 1024  # 1 GiB
FILE_TOO_LARGE_ERROR = "Uploaded file is too large to import once decompressed"


def _rows_from_json(data: bytes) -> pa.Table:
    """Parse an uploaded JSON file into an Arrow table, accepting the three shapes users export:
    a JSON array, a single JSON object, or newline-delimited JSON (one object per line)."""
    try:
        parsed = orjson.loads(data)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except orjson.JSONDecodeError:
        rows = [orjson.loads(line) for line in data.splitlines() if line.strip()]
    return table_from_py_list(rows)


def _iter_parquet_batches(data: bytes) -> Iterator[pa.RecordBatch]:
    parquet_file = pq.ParquetFile(pa.BufferReader(data))
    metadata = parquet_file.metadata
    # `total_byte_size` is the uncompressed size of each row group — sum it before decoding so a
    # compression bomb is rejected up front rather than after it has already been materialised.
    decoded_bytes = sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))
    if decoded_bytes > MAX_DECODED_BYTES:
        raise ValueError(f"{FILE_TOO_LARGE_ERROR} ({decoded_bytes} bytes decoded, limit {MAX_DECODED_BYTES}).")
    yield from parquet_file.iter_batches(batch_size=_BATCH_ROWS)


def _iter_uploaded_batches(data: bytes, file_format: str) -> Iterator[pa.RecordBatch]:
    """Decode an uploaded file into bounded Arrow batches. Streaming (rather than reading the whole
    table) keeps peak memory tied to `_BATCH_ROWS`, not to the file's decoded size."""
    if file_format == FORMAT_PARQUET:
        yield from _iter_parquet_batches(data)
    elif file_format == FORMAT_CSV:
        # First row is treated as the header — the common case for exported CSVs. The streaming reader
        # decodes block by block instead of materialising the full table.
        reader = pa_csv.open_csv(io.BytesIO(data))
        yield from reader
    elif file_format == FORMAT_JSON:
        # JSON has no metadata to size up front, but it is uploaded uncompressed, so its decoded size
        # is bounded by the upload cap. Parse once, then hand out bounded batches.
        yield from _rows_from_json(data).to_batches(max_chunksize=_BATCH_ROWS)
    else:
        raise ValueError(f"Unsupported file upload format: {file_format}")


def _read_uploaded_table(data: bytes, file_format: str) -> pa.Table:
    batches = list(_iter_uploaded_batches(data, file_format))
    return pa.Table.from_batches(batches) if batches else pa.table({})


class FileUploadSourceManager:
    """Reads a single user-uploaded object from PostHog's own data warehouse bucket and yields it to
    the import pipeline as batched Arrow tables. The read location is always scoped to the source's
    team, so a job can only ever reach that team's uploads."""

    def __init__(
        self,
        *,
        team_id: int,
        upload_id: str,
        filename: str,
        file_format: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._team_id = team_id
        self._upload_id = upload_id
        self._filename = filename
        self._file_format = file_format
        self._logger = logger

    async def get_items(self) -> AsyncGenerator[pa.Table]:
        path = build_file_upload_s3_path(self._team_id, self._upload_id, self._filename)

        async with aget_s3_client() as s3:
            async with await s3.open_async(path, "rb") as f:
                data = await f.read()

        row_count = 0
        for batch in _iter_uploaded_batches(data, self._file_format):
            row_count += batch.num_rows
            yield pa.Table.from_batches([batch])

        await self._logger.adebug(
            "file_upload_read",
            path=path,
            file_format=self._file_format,
            row_count=row_count,
        )


def file_upload_source(
    *,
    team_id: int,
    upload_id: str,
    filename: str,
    file_format: str,
    inputs: SourceInputs,
) -> SourceResponse:
    manager = FileUploadSourceManager(
        team_id=team_id,
        upload_id=upload_id,
        filename=filename,
        file_format=file_format,
        logger=inputs.logger,
    )

    return SourceResponse(
        name=inputs.schema_name,
        items=manager.get_items,
        # A flat file has no reliable unique key, so each sync fully replaces the table — re-uploading
        # and re-syncing reflects the new file rather than merging into the old rows.
        primary_keys=None,
    )
