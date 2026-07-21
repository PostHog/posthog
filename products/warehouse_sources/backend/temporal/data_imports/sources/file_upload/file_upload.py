from __future__ import annotations

from collections.abc import AsyncGenerator

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


def _rows_from_json(data: bytes) -> pa.Table:
    """Parse an uploaded JSON file into an Arrow table, accepting the three shapes users export:
    a JSON array, a single JSON object, or newline-delimited JSON (one object per line)."""
    try:
        parsed = orjson.loads(data)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except orjson.JSONDecodeError:
        rows = [orjson.loads(line) for line in data.splitlines() if line.strip()]
    return table_from_py_list(rows)


def _read_uploaded_table(data: bytes, file_format: str) -> pa.Table:
    if file_format == FORMAT_PARQUET:
        return pq.read_table(pa.BufferReader(data))
    if file_format == FORMAT_CSV:
        # First row is treated as the header — the common case for exported CSVs.
        return pa_csv.read_csv(pa.BufferReader(data))
    if file_format == FORMAT_JSON:
        return _rows_from_json(data)
    raise ValueError(f"Unsupported file upload format: {file_format}")


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

        table = _read_uploaded_table(data, self._file_format)
        await self._logger.adebug(
            "file_upload_read",
            path=path,
            file_format=self._file_format,
            row_count=table.num_rows,
            byte_count=table.nbytes,
        )

        for batch in table.to_batches(max_chunksize=_BATCH_ROWS):
            yield pa.Table.from_batches([batch], schema=table.schema)


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
