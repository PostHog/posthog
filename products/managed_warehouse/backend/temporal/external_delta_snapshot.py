from __future__ import annotations

import threading
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    import s3fs
    import deltalake


@frozen
class PreparedDeltaSnapshot:
    version: int
    delta_table_id: str
    paths: tuple[str, ...]
    row_count: int


def prepare_delta_snapshot(
    table: deltalake.DeltaTable,
    destination: s3fs.S3FileSystem,
    landing_uri: str,
    cancel_requested: threading.Event | None = None,
) -> PreparedDeltaSnapshot:
    version = table.version()
    delta_table_id = str(table.metadata().id)
    dataset = table.to_pyarrow_dataset()
    schema = dataset.schema
    paths: list[str] = []
    row_count = 0
    writer: pq.ParquetWriter | None = None
    output = None
    rows_in_file = 0
    try:
        for batch in dataset.scanner(
            batch_size=16384, batch_readahead=1, fragment_readahead=1, use_threads=False
        ).to_batches():
            if cancel_requested is not None and cancel_requested.is_set():
                raise TimeoutError("External snapshot preparation was canceled")
            if writer is None or rows_in_file >= 1_000_000:
                if writer is not None:
                    writer.close()
                    assert output is not None
                    output.close()
                path = str(PurePosixPath(landing_uri.removeprefix("s3://")) / f"part-{len(paths):06d}.parquet")
                output = destination.open(path, "wb")
                writer = pq.ParquetWriter(output, schema, compression="zstd")
                paths.append(f"s3://{path}")
                rows_in_file = 0
            writer.write_batch(batch)
            rows_in_file += batch.num_rows
            row_count += batch.num_rows
        if writer is None:
            path = f"{landing_uri.removeprefix('s3://')}/part-000000.parquet"
            with destination.open(path, "wb") as empty_output:
                pq.write_table(pa.Table.from_batches([], schema=schema), empty_output, compression="zstd")
            paths.append(f"s3://{path}")
    finally:
        if writer is not None:
            writer.close()
        if output is not None:
            output.close()
    return PreparedDeltaSnapshot(
        version=version, delta_table_id=delta_table_id, paths=tuple(paths), row_count=row_count
    )
