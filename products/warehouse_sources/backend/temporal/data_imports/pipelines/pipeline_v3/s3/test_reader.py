from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
from fsspec.implementations.memory import MemoryFileSystem
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import reader

_READER = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.reader"


@pytest.fixture(autouse=True)
def _fresh_shared_client():
    reader._shared_s3 = None
    yield
    reader._shared_s3 = None


def _client(open_error: Exception | None = None) -> MagicMock:
    s3 = MagicMock()
    if open_error is not None:
        s3.open.side_effect = open_error
    return s3


class TestReadParquetClientReuse:
    # Building an S3 client is an aiobotocore session plus credential resolution, which the loader
    # used to pay on every batch because the fsspec instance cache was cleared per message.

    @patch(f"{_READER}.pq.read_table", return_value=pa.table({"id": [1]}))
    @patch(f"{_READER}.get_s3_client")
    def test_consecutive_reads_share_one_client(self, mock_get_client: MagicMock, _read: MagicMock) -> None:
        mock_get_client.return_value = _client()

        reader.read_parquet("s3://bucket/a.parquet")
        reader.read_parquet("s3://bucket/b.parquet")
        reader.list_parquet_files("s3://bucket/folder")

        mock_get_client.assert_called_once_with(skip_instance_cache=True)

    @patch(f"{_READER}.pq.read_table", return_value=pa.table({"id": [1]}))
    @patch(f"{_READER}.get_s3_client")
    def test_a_client_whose_loop_is_gone_is_rebuilt_once(self, mock_get_client: MagicMock, _read: MagicMock) -> None:
        dead, live = _client(RuntimeError("Event loop is closed")), _client()
        mock_get_client.side_effect = [dead, live]

        table = reader.read_parquet("s3://bucket/a.parquet")

        assert table.num_rows == 1
        assert mock_get_client.call_count == 2
        live.open.assert_called_once_with("bucket/a.parquet", "rb")

    @pytest.mark.parametrize(
        "error",
        [RuntimeError("parquet footer is corrupt"), FileNotFoundError("bucket/a.parquet"), PermissionError("denied")],
        ids=["other_runtime_error", "missing_object", "permission"],
    )
    @patch(f"{_READER}.get_s3_client")
    def test_other_read_failures_keep_the_client_and_propagate(self, mock_get_client: MagicMock, error: Any) -> None:
        # A missing or forbidden object is not a client fault; rebuilding would only hide it and cost a
        # session per failing batch.
        mock_get_client.return_value = _client(error)

        with pytest.raises(type(error)):
            reader.read_parquet("s3://bucket/a.parquet")

        mock_get_client.assert_called_once()
        assert reader._shared_s3 is mock_get_client.return_value


def _hogql_types(table: pa.Table) -> dict[str, str]:
    schema = HogQLSchema()
    schema.add_pyarrow_table(table)
    return schema.to_hogql_types()


class TestReadParquetFirstValues:
    # A redelivered final batch types its string columns from this read. A column typed as a plain
    # string where the full batch gives JSON changes how every later query reads that column.

    @parameterized.expand(
        [
            ("json_in_the_first_row", ['{"a": 1}', "x", "y", "z"], "StringJSONDatabaseField"),
            ("json_array", ["[1, 2]", None, None, None], "StringJSONDatabaseField"),
            ("plain_string_before_json", ["plain", '{"a": 1}', None, None], "StringDatabaseField"),
            ("json_after_nulls_in_a_later_row_group", [None, None, None, '{"a": 1}'], "StringJSONDatabaseField"),
            ("json_after_a_null_in_the_same_row_group", [None, '{"a": 1}', "x", "y"], "StringJSONDatabaseField"),
            ("all_null", [None, None, None, None], "StringDatabaseField"),
            ("no_rows", [], "StringDatabaseField"),
        ]
    )
    @patch(f"{_READER}.get_s3_client")
    def test_types_each_column_as_the_full_batch_does(
        self, _name: str, payload: list[str | None], expected_payload_type: str, mock_get_client: MagicMock
    ) -> None:
        rows = len(payload)
        table = pa.table(
            {
                "id": pa.array(range(rows), pa.int64()),
                "payload": pa.array(payload, pa.string()),
                "other": pa.array(["plain"] * rows, pa.string()),
                "raw": pa.array([b"{"] * rows, pa.binary()),
                "seen_at": pa.array([None] * rows, pa.timestamp("us")),
                "tags": pa.array([["{"]] * rows, pa.list_(pa.string())),
                "a.b": pa.array(['{"a": 1}'] * rows, pa.string()),
                "a": pa.array([{"b": None}] * rows, pa.struct([("b", pa.string())])),
            }
        )
        store = MemoryFileSystem()
        with store.open("bucket/first-values.parquet", "wb") as f:
            pq.write_table(table, f, row_group_size=2)
        mock_get_client.return_value = store

        first_values = reader.read_parquet_first_values("s3://bucket/first-values.parquet")

        assert first_values.num_rows == 1
        assert first_values.schema.equals(table.schema)
        assert _hogql_types(first_values) == _hogql_types(table)
        assert _hogql_types(first_values)["payload"] == expected_payload_type
