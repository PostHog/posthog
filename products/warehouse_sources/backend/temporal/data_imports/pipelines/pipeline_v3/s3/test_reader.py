from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

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
