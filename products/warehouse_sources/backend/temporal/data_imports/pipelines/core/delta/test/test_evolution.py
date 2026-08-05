from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
    pyarrow_schema_from_arrow_exportable,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import evolution
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.evolution import (
    align_batch_to_delta_schema,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger


def _seed(delta_path: str, table: pa.Table, partition_by: str | None = None) -> deltalake.DeltaTable:
    deltalake.write_deltalake(delta_path, table, partition_by=partition_by)
    return deltalake.DeltaTable(delta_path)


class TestAlignBatchToDeltaSchema:
    @pytest.mark.asyncio
    async def test_fractional_values_widen_the_stored_integer_column(self, tmp_path: Path) -> None:
        # A cost column whose first sync only saw whole numbers is stored as int64; the source then
        # starts sending fractions. delta-rs would round them into the stored int64, so the loader
        # must convert the column instead of writing lossy data (or failing the sync forever).
        delta_path = str(tmp_path / "table")
        stored = _seed(
            delta_path,
            pa.table({"id": pa.array([1, 2], type=pa.int64()), "total_cost": pa.array([3, 4], type=pa.int64())}),
        )

        aligned = await align_batch_to_delta_schema(
            stored,
            pa.table({"id": pa.array([3], type=pa.int64()), "total_cost": pa.array([0.75], type=pa.float64())}),
            make_logger(),
        )

        assert aligned.widened_columns == {"total_cost": "double"}
        assert aligned.table.schema.field("total_cost").type == pa.float64()
        assert aligned.table.column("total_cost").to_pylist() == [0.75]

        rewritten = deltalake.DeltaTable(delta_path).to_pyarrow_table().sort_by("id")
        assert rewritten.schema.field("total_cost").type == pa.float64()
        assert rewritten.column("total_cost").to_pylist() == [3.0, 4.0]

    @pytest.mark.asyncio
    async def test_widening_keeps_the_table_partitioned(self, tmp_path: Path) -> None:
        # The conversion rewrites every file, so it has to re-apply the table's partitioning —
        # losing it would break the partition-by-partition merges every later sync runs.
        delta_path = str(tmp_path / "table")
        stored = _seed(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1, 2], type=pa.int64()),
                    "amount": pa.array([1, 2], type=pa.int64()),
                    "_ph_partition_key": pa.array(["a", "b"], type=pa.string()),
                }
            ),
            partition_by="_ph_partition_key",
        )

        await align_batch_to_delta_schema(
            stored,
            pa.table(
                {
                    "id": pa.array([3], type=pa.int64()),
                    "amount": pa.array([1.5], type=pa.float64()),
                    "_ph_partition_key": pa.array(["a"], type=pa.string()),
                }
            ),
            make_logger(),
        )

        rewritten = deltalake.DeltaTable(delta_path)
        assert rewritten.metadata().partition_columns == ["_ph_partition_key"]
        partition_values = cast(list[str], rewritten.to_pyarrow_table().column("_ph_partition_key").to_pylist())
        assert sorted(partition_values) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_stored_integers_beyond_double_precision_are_not_converted(self, tmp_path: Path) -> None:
        # Widening must never change stored values: an integer past double's exactly-representable
        # range would come back a different number, so the sync fails instead.
        delta_path = str(tmp_path / "table")
        stored = _seed(delta_path, pa.table({"value": pa.array([2**60 + 1], type=pa.int64())}))

        with pytest.raises(SchemaColumnTypeChangedException, match="Delete table and resync"):
            await align_batch_to_delta_schema(
                stored, pa.table({"value": pa.array([1.5], type=pa.float64())}), make_logger()
            )

        untouched = deltalake.DeltaTable(delta_path)
        assert pyarrow_schema_from_arrow_exportable(untouched.schema()).field("value").type == pa.int64()
        assert untouched.to_pyarrow_table().column("value").to_pylist() == [2**60 + 1]

    @pytest.mark.asyncio
    async def test_table_too_large_to_convert_fails_with_the_rebuild_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Converting blocks the batch that triggered it, so an oversized table is refused rather
        # than stalling the loader; the user still gets the action that fixes it.
        delta_path = str(tmp_path / "table")
        stored = _seed(delta_path, pa.table({"value": pa.array([1, 2], type=pa.int64())}))
        monkeypatch.setattr(evolution, "MAX_WIDENING_REWRITE_BYTES", 1)

        with pytest.raises(SchemaColumnTypeChangedException, match="Delete table and resync"):
            await align_batch_to_delta_schema(
                stored, pa.table({"value": pa.array([1.5], type=pa.float64())}), make_logger()
            )

        assert (
            pyarrow_schema_from_arrow_exportable(deltalake.DeltaTable(delta_path).schema()).field("value").type
            == pa.int64()
        )

    @pytest.mark.asyncio
    async def test_text_arriving_for_a_numeric_column_stays_terminal(self, tmp_path: Path) -> None:
        # Storing numbers as text changes what every query over the column means, so this one is
        # deliberately not converted — it needs the user to rebuild the table.
        delta_path = str(tmp_path / "table")
        stored = _seed(delta_path, pa.table({"value": pa.array([1, 2], type=pa.int64())}))

        with pytest.raises(SchemaColumnTypeChangedException, match="Delete table and resync"):
            await align_batch_to_delta_schema(
                stored, pa.table({"value": pa.array(["n/a"], type=pa.string())}), make_logger()
            )

        assert (
            pyarrow_schema_from_arrow_exportable(deltalake.DeltaTable(delta_path).schema()).field("value").type
            == pa.int64()
        )

    @pytest.mark.asyncio
    async def test_mixed_int_and_decimal_values_widen_to_decimal(self, tmp_path: Path) -> None:
        # A REST source that mixes ints and floats in one batch arrives as decimal (see
        # `_process_batch`), and the decimal has to keep room for the stored int64 range.
        delta_path = str(tmp_path / "table")
        stored = _seed(delta_path, pa.table({"value": pa.array([10**15], type=pa.int64())}))

        aligned = await align_batch_to_delta_schema(
            stored,
            pa.table({"value": pa.array([Decimal("19.99")], type=pa.decimal128(4, 2))}),
            make_logger(),
        )

        assert pa.types.is_decimal(aligned.table.schema.field("value").type)
        rewritten = deltalake.DeltaTable(delta_path).to_pyarrow_table()
        assert rewritten.column("value").to_pylist() == [Decimal("1000000000000000.00")]
