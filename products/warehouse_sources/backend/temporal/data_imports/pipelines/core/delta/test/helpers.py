from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef


def make_logger() -> MagicMock:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    logger.aexception = AsyncMock()
    return logger


def make_local_table_ref(delta_uri: str) -> DeltaTableRef:
    """DeltaTableRef that reads/writes a local filesystem path instead of S3."""
    table_ref = DeltaTableRef(resource_name="test", job=MagicMock(), logger=make_logger())
    patch.object(table_ref, "_get_delta_table_uri", new=AsyncMock(return_value=delta_uri)).start()
    patch.object(table_ref, "_get_credentials", new=MagicMock(return_value={})).start()
    table_ref.get_delta_table.cache_clear()
    return table_ref


def decimal_array(values: list, *, precision: int = 10, scale: int = 2, misaligned: bool) -> pa.Array:
    """Build a Decimal128 array. When `misaligned`, its data buffer is 8-byte but NOT
    16-byte aligned — the exact FFI case delta-rs (arrow-rs) aborts the worker on.

    pyarrow's allocator always returns 64-byte-aligned memory, so the only way to
    reproduce the bad case is to over-allocate and slice off 8 bytes, mimicking what
    arrives across the Arrow C Data Interface from polars / external producers.
    """
    aligned = pa.array(values, type=pa.decimal128(precision, scale))
    if not misaligned:
        return aligned

    data_buffer = aligned.buffers()[1]
    assert data_buffer is not None
    padded = pa.allocate_buffer(data_buffer.size + 16)
    memoryview(padded)[8 : 8 + data_buffer.size] = memoryview(data_buffer)
    misaligned_buffer = padded.slice(8, data_buffer.size)
    assert misaligned_buffer.address % 16 == 8
    # The validity buffer is legitimately None here (no nulls).
    buffers: list[pa.Buffer | None] = [None, misaligned_buffer]
    return pa.Array.from_buffers(pa.decimal128(precision, scale), len(values), buffers)


def table_is_misaligned(table: pa.Table) -> bool:
    return any(
        pa.types.is_decimal(table.field(i).type)
        and any((b := chunk.buffers()[1]) is not None and b.address % 16 for chunk in table.column(i).chunks)
        for i in range(table.num_columns)
    )
