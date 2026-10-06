import json
import errno
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import botocore.exceptions
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    ObjectStorePermissionDeniedError,
)
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

    @patch("tenacity.nap.time.sleep")
    @patch("pyarrow.parquet.write_table")
    def test_retries_read_timeout_then_succeeds(self, mock_write_table, _mock_sleep) -> None:
        # A read/connect timeout never gets s3fs's OSError translation (there's no response to
        # translate), so it reaches here as the raw botocore exception rather than an OSError.
        # It's exactly the transient blip this retry exists for and shouldn't fail the batch.
        f = MagicMock()
        s3 = _fake_s3([f, f])
        mock_write_table.side_effect = [
            botocore.exceptions.ReadTimeoutError(endpoint_url="https://example.com/part-0000.parquet"),
            None,
        ]

        _write_parquet_to_s3(s3, "bucket/part-0000.parquet", pa.table({"id": [1]}), "zstd")

        assert mock_write_table.call_count == 2

    @patch("pyarrow.parquet.write_table")
    def test_does_not_retry_ssl_error(self, mock_write_table) -> None:
        # SSLError is a ConnectionError subclass but usually means a bad/expired certificate,
        # not a network blip — retrying just delays a failure that will happen on every attempt.
        f = MagicMock()
        s3 = _fake_s3([f])
        mock_write_table.side_effect = botocore.exceptions.SSLError(
            endpoint_url="https://example.com/part-0000.parquet", error=Exception("certificate verify failed")
        )

        with pytest.raises(botocore.exceptions.SSLError):
            _write_parquet_to_s3(s3, "bucket/part-0000.parquet", pa.table({"id": [1]}), "zstd")

        assert mock_write_table.call_count == 1

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


class TestBatchByteSize:
    @parameterized.expand(
        [
            # s3fs spells the key in lowercase; reading S3's `Size` here recorded 0 bytes on every queue row.
            ("s3fs_lowercase_size", {"size": 2048}, 2048),
            ("raw_s3_head_shape", {"Size": 512}, 512),
            ("numeric_string", {"size": "64"}, 64),
            ("no_size_key", {"type": "file"}, 0),
            ("not_a_dict", None, 0),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer._write_parquet_to_s3"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.ensure_bucket")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.get_s3_client")
    def test_byte_size_comes_from_the_written_object(
        self,
        _name: str,
        file_info: dict | None,
        expected: int,
        mock_get_s3_client,
        _mock_ensure_bucket,
        _mock_write,
    ) -> None:
        mock_get_s3_client.return_value.info.return_value = file_info

        job = MagicMock()
        job.team_id = 1
        job.created_at = datetime(2026, 8, 5, tzinfo=UTC)
        writer = S3BatchWriter(MagicMock(), job, schema_id="schema-1", run_uuid="run-1")

        result = writer.write_batch(pa.table({"id": [1]}), 0)

        assert result.byte_size == expected


class TestWriteBatchPermissionDenied:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer._write_parquet_to_s3"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.ensure_bucket")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.get_s3_client")
    def test_write_batch_wraps_access_denied_instead_of_raising_raw_error(
        self,
        _mock_get_s3_client,
        _mock_ensure_bucket,
        mock_write,
    ) -> None:
        # The data warehouse bucket is PostHog's own, so an AccessDenied writing to it used to
        # escape write_batch as a raw PermissionError: it read to the customer as if their source
        # credentials were bad, and error tracking grouped a fresh issue per retry instead of one
        # stable title.
        mock_write.side_effect = PermissionError("Access Denied")

        job = MagicMock()
        job.team_id = 1
        job.created_at = datetime(2026, 8, 5, tzinfo=UTC)
        writer = S3BatchWriter(MagicMock(), job, schema_id="schema-1", run_uuid="run-1")

        with pytest.raises(ObjectStorePermissionDeniedError) as raised:
            writer.write_batch(pa.table({"id": [1]}), 0)

        assert raised.value.__cause__ is mock_write.side_effect


class TestSchemaAccumulation:
    @parameterized.expand(
        [
            ("int_then_double", pa.array([1, 2], type=pa.int64()), pa.array([1.5], type=pa.float64()), pa.float64()),
            ("int_then_string", pa.array([1], type=pa.int64()), pa.array(["2"], type=pa.string()), pa.string()),
            ("double_then_string", pa.array([1.5], type=pa.float64()), pa.array(["2"], type=pa.string()), pa.string()),
            ("string_then_double", pa.array(["2"], type=pa.string()), pa.array([1.5], type=pa.float64()), pa.string()),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer._write_parquet_to_s3"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.ensure_bucket")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.get_s3_client")
    def test_accumulated_schema_resolves_batches_that_disagree_on_a_column(
        self,
        _name: str,
        first: pa.Array,
        second: pa.Array,
        expected_type: pa.DataType,
        mock_get_s3_client,
        _mock_ensure_bucket,
        _mock_write,
    ) -> None:
        # Batches infer their own types, so a sparse column can land double in one batch and string
        # in the next. Folding those schemas together used to abort the whole table's sync with
        # ArrowTypeError: numeric widens where it can, and falls back to text where it can't.
        mock_get_s3_client.return_value.info.return_value = {"Size": 1}

        job = MagicMock()
        job.team_id = 1
        job.created_at = datetime(2026, 8, 5, tzinfo=UTC)
        job.workflow_run_id = "run-1"

        writer = S3BatchWriter(MagicMock(), job, schema_id="schema-1", run_uuid="run-1")

        writer.write_batch(pa.table({"consumed_quantity": first}), 0)
        writer.write_batch(pa.table({"consumed_quantity": second}), 1)

        schema = writer.get_schema()
        assert schema is not None
        assert schema.field("consumed_quantity").type == expected_type
