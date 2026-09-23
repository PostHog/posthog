from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
import pyarrow.compute as pc

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.scd2 import Scd2DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    decimal_array,
    make_local_table_ref,
    table_is_misaligned,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import commit_matches

_TS_TYPE = pa.timestamp("us", tz="UTC")


def _make_writer(delta_uri: str) -> Scd2DeltaWriter:
    return Scd2DeltaWriter(make_local_table_ref(delta_uri), valid_from_column="valid_from", valid_to_column="valid_to")


class TestScd2Write:
    @pytest.mark.asyncio
    async def test_write_misaligned_decimal_to_local_delta(self, tmp_path: Path) -> None:
        # The SCD2 write carries its own realignment guard; without it the
        # close-existing merge would hand delta-rs a misaligned decimal and abort the worker.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        # Seed a current (valid_to IS NULL) row for id=1 so the new batch closes it.
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "amount": decimal_array([5], misaligned=False),
                    "valid_from": pa.array([ts1], type=_TS_TYPE),
                    "valid_to": pa.array([None], type=_TS_TYPE),
                }
            ),
        )

        batch = pa.table(
            {
                "id": pa.array([1]),
                "amount": decimal_array([7], misaligned=True),
                "valid_from": pa.array([ts2], type=_TS_TYPE),
                "valid_to": pa.array([None], type=_TS_TYPE),
            }
        )
        assert table_is_misaligned(batch) is True

        result = await _make_writer(delta_path).write(data=batch, primary_keys=["id"])

        final = result.to_pyarrow_table()
        # The seeded row is closed (valid_to set) and the new misaligned row is appended.
        assert final.num_rows == 2
        assert set(final.column("amount").to_pylist()) == {5, 7}
        closed = final.filter(pc.equal(final.column("amount"), pa.scalar(Decimal("5.00"), type=pa.decimal128(10, 2))))
        assert closed.column("valid_to").to_pylist() == [ts2]

    @pytest.mark.asyncio
    async def test_write_batch_declaring_a_null_column_not_null(self, tmp_path: Path) -> None:
        # CDC reads SQL sources, whose batch schema copies the source database's is_nullable
        # metadata, so a column can claim NOT NULL and still arrive holding nulls. Both delta
        # calls in the SCD2 write reject that batch: write_deltalake raises and merge panics.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "note": pa.array(["first"]),
                    "valid_from": pa.array([ts1], type=_TS_TYPE),
                    "valid_to": pa.array([None], type=_TS_TYPE),
                }
            ),
        )

        batch_fields: list[pa.Field] = [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("note", pa.string(), nullable=False),
            pa.field("valid_from", _TS_TYPE, nullable=False),
            pa.field("valid_to", _TS_TYPE, nullable=True),
        ]
        batch = pa.table(
            {"id": [1], "note": [None], "valid_from": [ts2], "valid_to": [None]},
            schema=pa.schema(batch_fields),
        )

        result = await _make_writer(delta_path).write(data=batch, primary_keys=["id"])

        final = result.to_pyarrow_table()
        assert final.num_rows == 2
        assert sorted(final.column("note").to_pylist(), key=lambda x: x is not None) == [None, "first"]

    @pytest.mark.asyncio
    async def test_only_terminal_append_commit_carries_metadata(self, tmp_path: Path) -> None:
        # SCD2 is a two-step write (close-existing merge, then append). If the intermediate
        # close merge were tagged with (run_uuid, batch_index) and the writer crashed before
        # the append, Kafka redelivery would find the tagged commit via
        # has_batch_been_committed, treat the batch as already written, and silently skip
        # the append — data loss. Only the terminal append commit may carry the metadata.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "valid_from": pa.array([ts1], type=_TS_TYPE),
                    "valid_to": pa.array([None], type=_TS_TYPE),
                }
            ),
        )
        batch = pa.table(
            {
                "id": pa.array([1]),
                "valid_from": pa.array([ts2], type=_TS_TYPE),
                "valid_to": pa.array([None], type=_TS_TYPE),
            }
        )
        metadata = {"run_uuid": "r1", "batch_index": "0"}

        await _make_writer(delta_path).write(data=batch, primary_keys=["id"], commit_metadata=metadata)

        history = deltalake.DeltaTable(delta_path).history()
        # Newest first: [append (WRITE), close (MERGE), seed (WRITE)]. commit_matches is the
        # same layout-agnostic check has_batch_been_committed uses for redelivery dedup.
        tagged = [c["operation"] for c in history if commit_matches(c, metadata)]
        assert tagged == ["WRITE"]
        assert any(c["operation"] == "MERGE" for c in history)
