import io
import uuid
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import build_buffer_file_name

_CMD = "products.warehouse_sources.backend.management.commands.validate_cdc_buffer"


def _parquet_bytes(rows: int) -> bytes:
    buf = io.BytesIO()
    table = pa.table(
        {"id": pa.array(range(rows), type=pa.int64()), CDC_SEQ_COLUMN: pa.array(range(rows), type=pa.int64())}
    )
    pq.write_table(table, buf)
    return buf.getvalue()


def _fake_s3(files: dict[str, bytes]) -> MagicMock:
    """files: key (no protocol) -> parquet bytes"""
    s3 = MagicMock()

    def ls(prefix, detail=True):
        matching = [key for key in files if key.startswith(prefix)]
        if not matching:
            raise FileNotFoundError(prefix)
        return [{"Key": key, "type": "file", "LastModified": None} for key in matching]

    @contextmanager
    def open_(key, mode):
        yield io.BytesIO(files[key])

    s3.ls = ls
    s3.open = open_
    return s3


def _schema_mock(mode: str = "consolidated", cdc_mode: str = "streaming"):
    schema = MagicMock()
    schema.id = uuid.uuid4()
    schema.team_id = 1
    schema.name = "users"
    schema.cdc_table_mode = mode
    schema.cdc_mode = cdc_mode
    return schema


class TestValidateCDCBuffer:
    def _run(self, schema, files: dict[str, bytes], legacy: dict[tuple[str, str], int]):
        source = MagicMock()
        source.id = uuid.uuid4()

        with (
            patch(f"{_CMD}.ExternalDataSource") as MockSource,
            patch(f"{_CMD}.ExternalDataSchema") as MockSchema,
            patch(f"{_CMD}.get_s3_client", return_value=_fake_s3(files)),
            patch.object(
                __import__(_CMD, fromlist=["Command"]).Command,
                "_fetch_legacy_row_sums",
                return_value=legacy,
            ),
        ):
            MockSource.objects.get.return_value = source
            MockSchema.objects.filter.return_value = [schema]
            MockSchema.SyncType.CDC = "cdc"
            call_command("validate_cdc_buffer", "--source-id", str(source.id))

    def _key(self, schema, name: str) -> str:
        from django.conf import settings

        return f"{settings.DATAWAREHOUSE_BUCKET}/cdc_producer/{schema.team_id}/{schema.id}/{name}"

    def test_passes_on_consistent_buffer(self):
        schema = _schema_mock(mode="both")
        files = {
            self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3),
            self._key(schema, build_buffer_file_name(200, 300, 1)): _parquet_bytes(2),
        }
        # scd2 lane keeps one row per event: exact match. consolidated deduped down to 4.
        legacy = {(str(schema.id), "scd2"): 5, (str(schema.id), "consolidated"): 4}
        self._run(schema, files, legacy)

    def test_fails_on_scd2_mismatch(self):
        schema = _schema_mock(mode="cdc_only")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {(str(schema.id), "scd2"): 5})

    def test_fails_when_buffer_below_consolidated(self):
        schema = _schema_mock(mode="consolidated")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(2)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {(str(schema.id), "consolidated"): 5})

    def test_fails_on_overlapping_ranges(self):
        schema = _schema_mock(mode="consolidated")
        files = {
            self._key(schema, build_buffer_file_name(100, 250, 0)): _parquet_bytes(1),
            self._key(schema, build_buffer_file_name(200, 300, 0)): _parquet_bytes(1),
        }
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {})

    def test_shared_boundary_is_legal(self):
        # A split transaction's batches share its commit position — not an overlap.
        schema = _schema_mock(mode="consolidated")
        files = {
            self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(1),
            self._key(schema, build_buffer_file_name(200, 200, 1)): _parquet_bytes(1),
        }
        self._run(schema, files, {})

    def test_snapshot_schema_skips_row_reconciliation(self):
        # Snapshot phase defers legacy dispatch, so counts legitimately diverge.
        schema = _schema_mock(mode="cdc_only", cdc_mode="snapshot")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3)}
        self._run(schema, files, {(str(schema.id), "scd2"): 99})

    def test_fails_on_foreign_file(self):
        schema = _schema_mock(mode="consolidated")
        files = {self._key(schema, "part-0000.parquet"): _parquet_bytes(1)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {})
