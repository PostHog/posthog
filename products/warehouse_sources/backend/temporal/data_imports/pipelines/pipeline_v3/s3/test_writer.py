import json
import errno
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer import (
    S3BatchWriter,
    _write_parquet_to_s3,
    build_schema_dict,
)


def _fake_s3(open_side_effect: list) -> MagicMock:
    s3 = MagicMock()
    s3.open.return_value.__enter__.side_effect = open_side_effect
    # A MagicMock's auto-mocked __exit__ returns a truthy MagicMock by default, which would
    # suppress the exception pyarrow.parquet.write_table raises inside the `with` block.
    s3.open.return_value.__exit__.return_value = False
    return s3


class TestWriteParquetToS3:
    @patch("tenacity.nap.time.sleep")
    @patch("pyarrow.parquet.write_table")
    def test_retries_transient_os_error_then_succeeds(self, mock_write_table, _mock_sleep) -> None:
        # s3fs translates a truncated-upload S3 response (e.g. IncompleteBody) into a plain
        # OSError; a single dropped connection shouldn't fail the whole batch write.
        f = MagicMock()
        s3 = _fake_s3([f, f])
        mock_write_table.side_effect = [OSError(errno.EINVAL, "The request body terminated unexpectedly"), None]

        _write_parquet_to_s3(s3, "bucket/part-0000.parquet", pa.table({"id": [1]}), "zstd")

        assert mock_write_table.call_count == 2

    @patch("tenacity.nap.time.sleep")
    @patch("pyarrow.parquet.write_table")
    def test_reraises_after_persistent_os_error(self, mock_write_table, _mock_sleep) -> None:
        f = MagicMock()
        s3 = _fake_s3([f, f, f, f])
        mock_write_table.side_effect = OSError(errno.EINVAL, "The request body terminated unexpectedly")

        with pytest.raises(OSError):
            _write_parquet_to_s3(s3, "bucket/part-0000.parquet", pa.table({"id": [1]}), "zstd")

        assert mock_write_table.call_count == 4

    @patch("pyarrow.parquet.write_table")
    def test_does_not_retry_permission_error(self, mock_write_table) -> None:
        # PermissionError (e.g. AccessDenied/InvalidAccessKeyId) is an OSError subclass but not
        # transient — retrying it just delays a failure that will happen on every attempt.
        f = MagicMock()
        s3 = _fake_s3([f])
        mock_write_table.side_effect = PermissionError("Access Denied")

        with pytest.raises(PermissionError):
            _write_parquet_to_s3(s3, "bucket/part-0000.parquet", pa.table({"id": [1]}), "zstd")

        assert mock_write_table.call_count == 1


class TestBuildSchemaDict:
    def test_field_metadata_is_json_serializable(self) -> None:
        schema = pa.schema([pa.field("id", pa.int64(), metadata={"comment": "primary key"})])

        schema_dict = build_schema_dict(schema)

        # Would raise "keys must be str ... not bytes" if the bytes metadata wasn't decoded.
        json.dumps(schema_dict)
        assert schema_dict["fields"][0]["metadata"] == {"comment": "primary key"}

    def test_field_without_metadata_stays_none(self) -> None:
        schema = pa.schema([pa.field("id", pa.int64())])

        assert build_schema_dict(schema)["fields"][0]["metadata"] is None


class TestSchemaAccumulation:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer._write_parquet_to_s3"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.ensure_bucket")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.get_s3_client")
    def test_accumulated_schema_promotes_int_to_double_across_batches(
        self, mock_get_s3_client, _mock_ensure_bucket, _mock_write
    ) -> None:
        # Two batches of the same column can infer different numeric types within one run (whole
        # values -> int64, later fractional values -> double). Unifying them must widen to double
        # rather than raising ArrowTypeError, which would crash the whole extraction.
        mock_get_s3_client.return_value.info.return_value = {"Size": 1}

        job = MagicMock()
        job.team_id = 1
        job.created_at = datetime(2026, 8, 5, tzinfo=UTC)
        job.workflow_run_id = "run-1"

        writer = S3BatchWriter(MagicMock(), job, schema_id="schema-1", run_uuid="run-1")

        writer.write_batch(pa.table({"consumed_quantity": pa.array([1, 2], type=pa.int64())}), 0)
        writer.write_batch(pa.table({"consumed_quantity": pa.array([1.5, 2.5], type=pa.float64())}), 1)

        schema = writer.get_schema()
        assert schema is not None
        assert schema.field("consumed_quantity").type == pa.float64()
