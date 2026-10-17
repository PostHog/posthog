from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.row_hash import compute_row_hashes

_TS = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)


class TestComputeRowHashes:
    @parameterized.expand(
        [
            (
                "column_reorder",
                pa.table({"a": pa.array([1]), "b": pa.array(["x"])}),
                pa.table({"b": pa.array(["x"]), "a": pa.array([1])}),
            ),
            (
                "integer_widening",
                pa.table({"a": pa.array([7], type=pa.int32())}),
                pa.table({"a": pa.array([7], type=pa.int64())}),
            ),
            (
                "integer_to_decimal",
                pa.table({"a": pa.array([100], type=pa.int64())}),
                pa.table({"a": pa.array([Decimal("100.00")], type=pa.decimal128(10, 2))}),
            ),
            (
                "decimal_scale_widening",
                pa.table({"a": pa.array([Decimal("5.10")], type=pa.decimal128(10, 2))}),
                pa.table({"a": pa.array([Decimal("5.1000")], type=pa.decimal128(38, 4))}),
            ),
            (
                "small_decimal_scale_widening",
                pa.table({"a": pa.array([Decimal("0.0000001")], type=pa.decimal128(10, 7))}),
                pa.table({"a": pa.array([Decimal("0.0000001")], type=pa.decimal128(10, 8))}),
            ),
            (
                "float_widening",
                pa.table({"a": pa.array([1.5], type=pa.float32())}),
                pa.table({"a": pa.array([1.5], type=pa.float64())}),
            ),
            (
                "timestamp_unit",
                pa.table({"a": pa.array([_TS], type=pa.timestamp("ms", tz="UTC"))}),
                pa.table({"a": pa.array([_TS], type=pa.timestamp("us", tz="UTC"))}),
            ),
            (
                "date_unit",
                pa.table({"a": pa.array([date(2026, 1, 1)], type=pa.date32())}),
                pa.table({"a": pa.array([date(2026, 1, 1)], type=pa.date64())}),
            ),
            (
                "string_width",
                pa.table({"a": pa.array(["x"], type=pa.string())}),
                pa.table({"a": pa.array(["x"], type=pa.large_string())}),
            ),
            (
                "added_null_column",
                pa.table({"a": pa.array([1])}),
                pa.table({"a": pa.array([1]), "b": pa.array([None], type=pa.string())}),
            ),
            (
                "excluded_column",
                pa.table({"a": pa.array([1]), "synced_at": pa.array([1])}),
                pa.table({"a": pa.array([1]), "synced_at": pa.array([2])}),
            ),
            (
                "nested_key_order",
                pa.table({"a": pa.array([{"x": 1, "y": [1, 2]}])}),
                pa.table({"a": pa.array([{"y": [1, 2], "x": 1}])}),
            ),
        ]
    )
    def test_schema_only_difference_keeps_the_hash(self, _name: str, before: pa.Table, after: pa.Table) -> None:
        exclude = {"synced_at"}
        assert compute_row_hashes(before, exclude).to_pylist() == compute_row_hashes(after, exclude).to_pylist()

    @parameterized.expand(
        [
            ("value", pa.table({"a": pa.array(["x"])}), pa.table({"a": pa.array(["y"])})),
            ("whole_decimal_zeros", pa.table({"a": pa.array([Decimal("100")])}), pa.table({"a": pa.array([1])})),
            ("null_to_empty_string", pa.table({"a": pa.array([None], type=pa.string())}), pa.table({"a": [""]})),
            (
                "value_moves_to_another_column",
                pa.table({"a": pa.array(["x"]), "b": pa.array([None], type=pa.string())}),
                pa.table({"a": pa.array([None], type=pa.string()), "b": pa.array(["x"])}),
            ),
            (
                "value_that_spells_a_second_column",
                pa.table({"a": pa.array(["x"]), "b": pa.array(["y"])}),
                pa.table({"a": pa.array(["xb\x1fy"]), "b": pa.array([None], type=pa.string())}),
            ),
        ]
    )
    def test_content_difference_changes_the_hash(self, _name: str, before: pa.Table, after: pa.Table) -> None:
        assert compute_row_hashes(before).to_pylist() != compute_row_hashes(after).to_pylist()

    def test_hashes_each_row_of_a_chunked_table_on_its_own(self) -> None:
        one = pa.table({"a": pa.array([1, 2]), "b": pa.array(["x", None])})
        chunked = pa.concat_tables([one, pa.table({"a": pa.array([1]), "b": pa.array(["x"])})])

        first, second, third = compute_row_hashes(chunked).to_pylist()

        assert first == third
        assert first != second
