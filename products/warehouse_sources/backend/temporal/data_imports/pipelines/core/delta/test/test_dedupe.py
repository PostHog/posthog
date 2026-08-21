import pytest

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.dedupe import (
    repair_duplicate_primary_keys,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
    make_logger,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    append_partition_key_to_table,
)

MAY = 1714521600
JUNE = 1717200000


def _rows(ids: list[str], created: list[int], *, region: list[str] | None = None) -> pa.Table:
    columns: dict[str, pa.Array] = {
        "id": pa.array(ids, pa.string()),
        "created": pa.array(created, pa.int64()),
        "balance": pa.array([1] * len(ids), pa.int64()),
    }
    if region is not None:
        columns["region"] = pa.array(region, pa.string())
    return pa.table(columns)


def _with_partition_key(table: pa.Table) -> pa.Table:
    result = append_partition_key_to_table(
        table=table,
        partition_count=1,
        partition_size=1,
        partition_keys=["created"],
        partition_mode="datetime",
        partition_format="month",
        logger=make_logger(),
    )
    assert result is not None
    return result.table


async def _append_chunk(uri: str, data: pa.Table, *, primary_keys: list[str], overwrite: bool) -> None:
    ref = make_local_table_ref(uri)
    ref._is_first_sync = True
    await DeltaWriter(ref).write(
        data=data,
        write_type="incremental",
        should_overwrite_table=overwrite,
        primary_keys=primary_keys,
    )


async def _build_table(
    uri: str, chunks: list[pa.Table], *, primary_keys: list[str] | None = None, partitioned: bool = True
) -> None:
    keys = primary_keys or ["id"]
    for index, chunk in enumerate(chunks):
        data = _with_partition_key(chunk) if partitioned else chunk
        await _append_chunk(uri, data, primary_keys=keys, overwrite=index == 0)


def _counts(uri: str, key_columns: list[str]) -> tuple[int, int]:
    table = deltalake.DeltaTable(uri).to_pyarrow_table()
    distinct = table.group_by(key_columns).aggregate([]).num_rows
    return table.num_rows, distinct


@pytest.mark.asyncio
@pytest.mark.parametrize("partitioned", [True, False])
async def test_collapses_keys_duplicated_across_appended_chunks(tmp_path, partitioned):
    uri = str(tmp_path / "t")
    await _build_table(
        uri,
        [
            _rows(["a", "busy"], [MAY, MAY]),
            _rows(["b", "busy"], [JUNE, MAY]),
            _rows(["c", "busy"], [MAY, MAY]),
        ],
        partitioned=partitioned,
    )
    assert _counts(uri, ["id"]) == (6, 4)

    dropped = await repair_duplicate_primary_keys(make_local_table_ref(uri), ["id"], make_logger())

    assert dropped == 2
    assert _counts(uri, ["id"]) == (4, 4)


@pytest.mark.asyncio
async def test_keeps_every_column_of_the_surviving_row(tmp_path):
    uri = str(tmp_path / "t")
    await _build_table(uri, [_rows(["busy"], [MAY]), _rows(["busy"], [MAY])])

    await repair_duplicate_primary_keys(make_local_table_ref(uri), ["id"], make_logger())

    table = deltalake.DeltaTable(uri).to_pyarrow_table()
    assert table.num_rows == 1
    assert set(table.column_names) >= {"id", "created", "balance", PARTITION_KEY}
    assert table.column("created").to_pylist() == [MAY]


@pytest.mark.asyncio
async def test_leaves_a_table_without_duplicates_unwritten(tmp_path):
    uri = str(tmp_path / "t")
    await _build_table(uri, [_rows(["a"], [MAY]), _rows(["b"], [JUNE])])
    version_before = deltalake.DeltaTable(uri).version()

    dropped = await repair_duplicate_primary_keys(make_local_table_ref(uri), ["id"], make_logger())

    assert dropped == 0
    assert deltalake.DeltaTable(uri).version() == version_before


@pytest.mark.asyncio
async def test_collapses_on_the_full_composite_key(tmp_path):
    uri = str(tmp_path / "t")
    await _build_table(
        uri,
        [
            _rows(["k", "k"], [MAY, MAY], region=["us", "eu"]),
            _rows(["k"], [MAY], region=["us"]),
        ],
        primary_keys=["id", "region"],
    )
    assert _counts(uri, ["id", "region"]) == (3, 2)

    dropped = await repair_duplicate_primary_keys(make_local_table_ref(uri), ["id", "region"], make_logger())

    assert dropped == 1
    assert _counts(uri, ["id", "region"]) == (2, 2)


@pytest.mark.asyncio
async def test_skips_a_key_that_is_not_a_column_of_the_table(tmp_path):
    uri = str(tmp_path / "t")
    await _build_table(uri, [_rows(["busy"], [MAY]), _rows(["busy"], [MAY])])

    dropped = await repair_duplicate_primary_keys(make_local_table_ref(uri), ["no_such_column"], make_logger())

    assert dropped == 0
    assert _counts(uri, ["id"]) == (2, 1)


@pytest.mark.asyncio
async def test_returns_zero_when_the_table_does_not_exist(tmp_path):
    dropped = await repair_duplicate_primary_keys(
        make_local_table_ref(str(tmp_path / "missing")), ["id"], make_logger()
    )

    assert dropped == 0
