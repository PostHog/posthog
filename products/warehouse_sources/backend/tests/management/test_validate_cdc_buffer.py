import io
import uuid
import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

import psycopg
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


def _fake_s3(files: dict[str, bytes | tuple[bytes, datetime | None]]) -> MagicMock:
    """files: key (no protocol) -> parquet bytes, or (bytes, LastModified)."""

    def _content(value) -> bytes:
        return value[0] if isinstance(value, tuple) else value

    def _modified(value) -> datetime | None:
        return value[1] if isinstance(value, tuple) else None

    s3 = MagicMock()

    def ls(prefix, detail=True):
        matching = [key for key in files if key.startswith(prefix)]
        if not matching:
            raise FileNotFoundError(prefix)
        return [{"Key": key, "type": "file", "LastModified": _modified(files[key])} for key in matching]

    @contextmanager
    def open_(key, mode):
        yield io.BytesIO(_content(files[key]))

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
    def _run(self, schema, files, legacy: dict[tuple[str, str], int], retried: dict[str, int] | None = None):
        source = MagicMock()
        source.id = uuid.uuid4()

        with (
            patch(f"{_CMD}.ExternalDataSource") as MockSource,
            patch(f"{_CMD}.ExternalDataSchema") as MockSchema,
            patch(f"{_CMD}.get_s3_client", return_value=_fake_s3(files)),
            patch.object(
                __import__(_CMD, fromlist=["Command"]).Command,
                "_fetch_legacy_row_sums",
                return_value=(legacy, retried or {}),
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

    def test_scd2_mismatch_downgrades_to_warning_after_a_retry(self):
        # Legacy re-inserts replayed rows on activity retry while buffer files
        # overwrite, so a re-dispatched batch makes the exact match only warn.
        schema = _schema_mock(mode="cdc_only")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3)}
        self._run(schema, files, {(str(schema.id), "scd2"): 5}, retried={str(schema.id): 1})

    def test_scd2_mismatch_still_fails_when_no_batch_was_retried(self):
        # Regression: the downgrade used to key on the count of distinct run_uuids, which a
        # healthy 5-min source increments every tick — so any window longer than one tick
        # waived the exact match entirely and the gate asserted nothing.
        schema = _schema_mock(mode="cdc_only")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {(str(schema.id), "scd2"): 5}, retried={str(schema.id): 0})

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

    def test_fails_on_inverted_range(self):
        schema = _schema_mock(mode="consolidated")
        # build_buffer_file_name refuses inverted ranges, so name it by hand.
        name = f"{300:020d}-{200:020d}-{0:06d}.parquet"
        files = {self._key(schema, name): _parquet_bytes(1)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {})

    def test_shared_boundary_is_legal(self):
        # A split transaction's batches share its commit position — not an overlap.
        schema = _schema_mock(mode="consolidated")
        files = {
            self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(1),
            self._key(schema, build_buffer_file_name(200, 200, 1)): _parquet_bytes(1),
        }
        self._run(schema, files, {(str(schema.id), "consolidated"): 2})

    def test_buffered_rows_with_no_legacy_dispatches_is_a_violation(self):
        # Streaming flushes dispatch legacy immediately: buffer rows with zero legacy
        # rows means the legacy lane stalled — absence must not skip the comparison.
        schema = _schema_mock(mode="both")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {(str(schema.id), "scd2"): 3})  # scd2 fine, consolidated lane absent

    def test_snapshot_schema_skips_row_reconciliation(self):
        # Snapshot phase defers legacy dispatch, so counts legitimately diverge.
        schema = _schema_mock(mode="cdc_only", cdc_mode="snapshot")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): _parquet_bytes(3)}
        self._run(schema, files, {(str(schema.id), "scd2"): 99})

    def test_empty_buffer_with_legacy_rows_is_a_violation_not_a_crash(self):
        # Day-one state: shadow just enabled, no files yet, legacy still dispatching.
        schema = _schema_mock(mode="cdc_only")
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, {}, {(str(schema.id), "scd2"): 5})

    def test_files_older_than_window_are_excluded(self):
        schema = _schema_mock(mode="cdc_only")
        old = datetime.now(UTC) - timedelta(hours=48)
        files = {
            self._key(schema, build_buffer_file_name(1, 50, 0)): (_parquet_bytes(7), old),
            self._key(schema, build_buffer_file_name(100, 200, 0)): (_parquet_bytes(3), None),
        }
        # Reconciles against only the in-window file (3 rows); counting the stale
        # 7 rows would make the exact match pass at the wrong sum.
        self._run(schema, files, {(str(schema.id), "scd2"): 3})

    def test_unreadable_file_is_a_violation_not_a_crash(self):
        schema = _schema_mock(mode="consolidated")
        files = {self._key(schema, build_buffer_file_name(100, 200, 0)): b"not a parquet file"}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {})

    def test_fails_on_foreign_file(self):
        schema = _schema_mock(mode="consolidated")
        files = {self._key(schema, "part-0000.parquet"): _parquet_bytes(1)}
        with pytest.raises(CommandError, match="violation"):
            self._run(schema, files, {})


@pytest.mark.django_db(transaction=True)
class TestFetchLegacyRowSums:
    """DB-backed: the SQL must count only sync_type='cdc' dispatches — snapshots
    (full_refresh) share the sourcebatch table and would otherwise inflate the
    consolidated lane into a guaranteed false violation during onboarding."""

    @pytest.fixture(autouse=True)
    def _tables(self):
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.test_jobs_db import (
            _ensure_tables,
            _get_test_database_url,
            _truncate_tables,
        )

        url = _get_test_database_url()
        with psycopg.Connection.connect(url, autocommit=True) as conn:
            _ensure_tables(conn)
            _truncate_tables(conn)
        self._url = url
        yield

    def _seed(self, rows: list[dict]) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.test_jobs_db import (
            _insert_batch,
        )

        async def seed() -> None:
            async with await psycopg.AsyncConnection.connect(self._url, autocommit=True) as conn:
                for row in rows:
                    await _insert_batch(conn, **row)

        asyncio.run(seed())

    def test_counts_only_cdc_dispatches_and_reports_no_retry(self):
        command_module = __import__(_CMD, fromlist=["Command"])
        source = MagicMock()
        source.id = "source-1"
        schema_id = "schema-1"

        self._seed(
            [
                {
                    "schema_id": schema_id,
                    "sync_type": "cdc",
                    "resource_name": "users",
                    "row_count": 10,
                    "run_uuid": "r1",
                },
                {
                    "schema_id": schema_id,
                    "sync_type": "cdc",
                    "resource_name": "users_cdc",
                    "row_count": 7,
                    "run_uuid": "r1",
                    "batch_index": 1,
                },
                # Snapshot dispatch for the same schema: must NOT count.
                {
                    "schema_id": schema_id,
                    "sync_type": "full_refresh",
                    "resource_name": "users",
                    "row_count": 9999,
                    "run_uuid": "r2",
                    "batch_index": 2,
                },
                # Second cdc run: bumps the distinct-run count.
                {
                    "schema_id": schema_id,
                    "sync_type": "cdc",
                    "resource_name": "users",
                    "row_count": 5,
                    "run_uuid": "r3",
                    "batch_index": 3,
                },
            ]
        )

        with patch.object(command_module, "WAREHOUSE_SOURCES_DATABASE_URL", self._url):
            sums, retried_batches = command_module.Command()._fetch_legacy_row_sums(
                source, datetime.now(UTC) - timedelta(hours=1)
            )

        assert sums == {(schema_id, "consolidated"): 15, (schema_id, "scd2"): 7}
        # Two distinct runs, but every (run_uuid, batch_index) dispatched once: no retry.
        assert retried_batches[schema_id] == 0

    def test_detects_a_redispatched_batch_as_a_retry(self):
        command_module = __import__(_CMD, fromlist=["Command"])
        source = MagicMock()
        source.id = "source-1"
        schema_id = "schema-1"

        self._seed(
            [
                {
                    "schema_id": schema_id,
                    "sync_type": "cdc",
                    "resource_name": "users_cdc",
                    "row_count": 7,
                    "run_uuid": "r1",
                    "batch_index": 0,
                },
                # Same (run_uuid, batch_index) dispatched again — the replay an activity
                # retry produces, and the only thing that legitimately skews the exact match.
                {
                    "schema_id": schema_id,
                    "sync_type": "cdc",
                    "resource_name": "users_cdc",
                    "row_count": 7,
                    "run_uuid": "r1",
                    "batch_index": 0,
                },
            ]
        )

        with patch.object(command_module, "WAREHOUSE_SOURCES_DATABASE_URL", self._url):
            sums, retried_batches = command_module.Command()._fetch_legacy_row_sums(
                source, datetime.now(UTC) - timedelta(hours=1)
            )

        assert sums == {(schema_id, "scd2"): 14}
        assert retried_batches[schema_id] == 1
