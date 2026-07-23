from typing import Any

import pytest
from unittest.mock import MagicMock, Mock, patch

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import (
    DuckgresColumn,
    _ensure_duckgres_apply_table,
    _insert_batch,
    _mark_duckgres_batch_applied,
    _process_backfill_batch,
    _process_batch,
    _session_cache,
    _table_exists,
    process_batch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PendingBatch,
)


@pytest.fixture(autouse=True)
def _stub_schema_resolver():
    # _duckgres_schema_name now resolves the team's table_suffix via the ORM;
    # these are no-DB unit tests, so pin a deterministic schema name.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.duckgres_data_imports_schema",
        return_value="posthog_data_imports_team_1",
    ):
        yield


def _make_batch(**overrides: Any) -> PendingBatch:
    defaults: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "team_id": 1,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "job_id": "job-1",
        "run_uuid": "run-1",
        "batch_index": 0,
        "s3_path": "s3://bucket/path",
        "row_count": 100,
        "byte_size": 1024,
        "is_final_batch": False,
        "total_batches": None,
        "total_rows": None,
        "sync_type": "incremental",
        "cumulative_row_count": 0,
        "resource_name": "test_resource",
        "is_resume": False,
        "is_first_ever_sync": False,
        "metadata": {},
        "latest_attempt": 0,
    }
    defaults.update(overrides)
    return PendingBatch(**defaults)


def _make_schema() -> Mock:
    schema = Mock()
    schema.normalized_name = "customers"
    schema.source.source_type = "Stripe"
    schema.source.prefix = None
    return schema


def _make_conn() -> MagicMock:
    return MagicMock()


def _parquet_schema() -> list[DuckgresColumn]:
    return [DuckgresColumn("id", "BIGINT"), DuckgresColumn("email", "VARCHAR")]


class _RecordingTransaction:
    def __init__(self, conn: "_RecordingConn") -> None:
        self.conn = conn

    def __enter__(self) -> None:
        self.conn.in_transaction = True
        self.conn.events.append("transaction:start")

    def __exit__(self, *args: object) -> None:
        self.conn.events.append("transaction:end")
        self.conn.in_transaction = False


class _RecordingConn:
    def __init__(self) -> None:
        self.execute = MagicMock()
        self.events: list[str] = []
        self.in_transaction = False

    def transaction(self) -> _RecordingTransaction:
        return _RecordingTransaction(self)


def test_first_ever_incremental_batch_replaces_table() -> None:
    conn = _make_conn()
    batch = _make_batch(batch_index=0, is_first_ever_sync=True, is_resume=False, sync_type="incremental")

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table"
        ) as replace_table,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists"
        ) as table_exists,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch"
        ) as merge_batch,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch"
        ) as insert_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    replace_table.assert_called_once()
    table_exists.assert_not_called()
    merge_batch.assert_not_called()
    insert_batch.assert_not_called()


def test_existing_incremental_batch_zero_merges_after_first_sync() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=0,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table"
        ) as replace_table,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            create=True,
        ) as ensure_columns,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch"
        ) as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    replace_table.assert_not_called()
    ensure_columns.assert_called_once_with(conn, "posthog_data_imports_team_1", "stripe_customers", _parquet_schema())
    merge_batch.assert_called_once()


def test_first_ever_incremental_followup_batch_inserts_without_primary_keys() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=True,
        metadata={},
    )

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            create=True,
        ) as ensure_columns,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch"
        ) as insert_batch,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch"
        ) as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    ensure_columns.assert_called_once_with(conn, "posthog_data_imports_team_1", "stripe_customers", _parquet_schema())
    insert_batch.assert_called_once()
    merge_batch.assert_not_called()


def test_existing_incremental_table_merges_after_first_sync() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            create=True,
        ) as ensure_columns,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch"
        ) as insert_batch,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch"
        ) as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    ensure_columns.assert_called_once_with(conn, "posthog_data_imports_team_1", "stripe_customers", _parquet_schema())
    insert_batch.assert_not_called()
    merge_batch.assert_called_once()


def test_schema_evolution_merge_and_apply_marker_are_one_transaction() -> None:
    conn: Any = _RecordingConn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    def ensure_columns(*args: object) -> None:
        assert conn.in_transaction
        conn.events.append("ensure_columns")

    def merge_batch(*args: object) -> None:
        assert conn.in_transaction
        conn.events.append("merge")

    def mark_applied(*args: object, **kwargs: object) -> None:
        assert conn.in_transaction
        conn.events.append("mark")

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            side_effect=ensure_columns,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch",
            side_effect=merge_batch,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._mark_duckgres_batch_applied",
            side_effect=mark_applied,
        ),
    ):
        _process_batch(conn, batch, _make_schema())

    assert conn.events == ["transaction:start", "ensure_columns", "merge", "mark", "transaction:end"]


def test_missing_table_is_created_from_parquet() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._create_table_from_parquet"
        ) as create_table,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch"
        ) as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    create_table.assert_called_once()
    merge_batch.assert_not_called()


def test_insert_batch_uses_explicit_column_projection() -> None:
    conn = _make_conn()

    _insert_batch(conn, "warehouse", "customers", ["s3://bucket/path"], ["id", "email"])

    query = conn.execute.call_args.args[0]
    assert "SELECT *" not in repr(query)
    assert "s3://bucket/path" in repr(query)  # path is inlined as a literal now


def test_already_applied_batch_skips_duckgres_mutation() -> None:
    conn = _make_conn()
    batch = _make_batch(batch_index=0, is_first_ever_sync=True)

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table",
            create=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            create=True,
            return_value=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ) as read_schema,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table"
        ) as replace_table,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch"
        ) as insert_batch,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch"
        ) as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    read_schema.assert_not_called()
    replace_table.assert_not_called()
    insert_batch.assert_not_called()
    merge_batch.assert_not_called()


def test_marks_duckgres_batch_applied_after_successful_mutation() -> None:
    conn = _make_conn()
    batch = _make_batch(batch_index=0, is_first_ever_sync=True)

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table",
            create=True,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            create=True,
            return_value=False,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table"
        ) as replace_table,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._mark_duckgres_batch_applied",
            create=True,
        ) as mark_applied,
    ):
        _process_batch(conn, batch, _make_schema())

    replace_table.assert_called_once()
    mark_applied.assert_called_once_with(conn, "posthog_data_imports_team_1", batch=batch)


def test_duckgres_apply_marker_is_scoped_by_schema_id() -> None:
    conn = _make_conn()
    batch = _make_batch(schema_id="schema-1", run_uuid="run-1", batch_index=2)

    _ensure_duckgres_apply_table(conn, "warehouse")
    create_query = conn.execute.call_args.args[0]

    assert "schema_id" in repr(create_query)
    assert "PRIMARY KEY (schema_id, run_uuid, batch_index)" in repr(create_query)

    _mark_duckgres_batch_applied(conn, "warehouse", batch=batch)

    query = conn.execute.call_args.args[0]
    assert "ON CONFLICT (schema_id, run_uuid, batch_index)" in repr(query)
    assert conn.execute.call_args.args[1] == [
        "schema-1",
        "run-1",
        2,
        "00000000-0000-0000-0000-000000000001",
    ]


def _make_backfill_batch(**overrides: Any) -> PendingBatch:
    md = {
        "duckgres_backfill": True,
        "chunk_paths": ["s3://bucket/chunk_0.parquet"],
        "chunk_count": 3,
    }
    md.update(overrides.pop("metadata", {}))
    return _make_batch(
        job_id="duckgres-backfill",
        run_uuid="duckgres-backfill-schema-1-v7",
        sync_type="full_refresh",
        is_resume=True,
        metadata=md,
        **overrides,
    )


class TestBackfillProcessing:
    def test_first_chunk_creates_backfill_table_without_swap(self) -> None:
        conn = _make_conn()
        batch = _make_backfill_batch(batch_index=0)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
                return_value=_parquet_schema(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._mark_duckgres_batch_applied"
            ) as mark,
        ):
            _process_backfill_batch(conn, batch, _make_schema())

        executed = " ".join(repr(c.args[0]) for c in conn.execute.call_args_list)
        assert "stripe_customers__bf_schema1" in executed
        assert "CREATE OR REPLACE TABLE" in executed
        assert "RENAME TO" not in executed
        mark.assert_called_once()

    def test_last_chunk_swaps_and_marks_primed(self) -> None:
        conn = _make_conn()
        batch = _make_backfill_batch(batch_index=2, metadata={"chunk_paths": ["s3://bucket/chunk_2.parquet"]})

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
                return_value=_parquet_schema(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch"
            ) as insert,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._mark_duckgres_batch_applied"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill.mark_primed"
            ) as primed,
        ):
            _process_backfill_batch(conn, batch, _make_schema())

        executed = " ".join(repr(c.args[0]) for c in conn.execute.call_args_list)
        assert "DROP TABLE IF EXISTS" in executed
        assert "Identifier('stripe_customers')" in executed
        assert "RENAME TO" in executed
        insert.assert_called_once()
        primed.assert_called_once_with("schema-1", run_uuid="duckgres-backfill-schema-1-v7", chunks_applied=3)

    def test_already_applied_chunk_is_a_noop(self) -> None:
        conn = _make_conn()
        batch = _make_backfill_batch(batch_index=1)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch"
            ) as insert,
        ):
            _process_backfill_batch(conn, batch, _make_schema())

        insert.assert_not_called()


class TestLiveSessionReuse:
    """Reusing the duckgres session across a group's live batches removes the
    dominant per-batch fixed costs measured in prod on 2026-07-22: worker
    session create, the describe probe's cold catalog enumeration, and the
    first-write metadata touch (~20-40s combined per batch)."""

    @pytest.fixture(autouse=True)
    def _reset_cache_and_orm(self):
        _session_cache.clear()
        patches = [
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.close_old_connections"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.ExternalDataJob"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.Team"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._process_batch"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.setup_duckgres_session"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._create_extract_read_secret"
            ),
        ]
        self.mocks = [p.start() for p in patches]
        (_, self.mock_job, self.mock_team, self.mock_inner, self.mock_setup, self.mock_secret) = self.mocks
        self.mock_team.objects.only.return_value.get.return_value.organization_id = "org-a"
        yield
        for p in patches:
            p.stop()
        _session_cache.clear()

    def _connect_patch(self):
        return patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._connect_to_duckgres"
        )

    def test_consecutive_live_batches_reuse_one_connection_and_preamble(self):
        with self._connect_patch() as mock_connect:
            mock_connect.return_value = MagicMock()
            process_batch(_make_batch(batch_index=1))
            process_batch(_make_batch(batch_index=2))

        assert mock_connect.call_count == 1
        assert self.mock_setup.call_count == 1
        assert self.mock_secret.call_count == 1
        assert self.mock_inner.call_count == 2

    def test_groups_get_separate_connections(self):
        with self._connect_patch() as mock_connect:
            mock_connect.side_effect = [MagicMock(), MagicMock()]
            process_batch(_make_batch(schema_id="schema-1"))
            process_batch(_make_batch(schema_id="schema-2"))

        assert mock_connect.call_count == 2

    def test_failed_apply_drops_the_cached_connection(self):
        conn1, conn2 = MagicMock(), MagicMock()
        self.mock_inner.side_effect = [RuntimeError("apply failed"), None]
        with self._connect_patch() as mock_connect:
            mock_connect.side_effect = [conn1, conn2]
            with pytest.raises(RuntimeError):
                process_batch(_make_batch(batch_index=1))
            process_batch(_make_batch(batch_index=2))

        conn1.close.assert_called_once()
        assert mock_connect.call_count == 2

    def test_expired_session_is_replaced(self, monkeypatch):
        conn1, conn2 = MagicMock(), MagicMock()
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.time",
            MagicMock(monotonic=lambda: clock["now"]),
        )
        with self._connect_patch() as mock_connect:
            mock_connect.side_effect = [conn1, conn2]
            process_batch(_make_batch(batch_index=1))
            clock["now"] += 10_000  # far past both idle TTL and absolute age cap
            process_batch(_make_batch(batch_index=2))

        conn1.close.assert_called_once()
        assert mock_connect.call_count == 2

    def test_absolute_age_cap_survives_steady_reuse(self, monkeypatch):
        # The extract-read secret embeds expiring session credentials, so the
        # cap must track the ORIGINAL session creation, not the last reuse.
        conn1, conn2 = MagicMock(), MagicMock()
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.time",
            MagicMock(monotonic=lambda: clock["now"]),
        )
        with self._connect_patch() as mock_connect:
            mock_connect.side_effect = [conn1, conn2]
            for i in range(12):  # reuse every 61s: idle TTL never trips, age cap must
                process_batch(_make_batch(batch_index=i))
                clock["now"] += 61.0

        conn1.close.assert_called_once()
        assert mock_connect.call_count == 2

    def test_evict_stale_closes_idle_sessions_without_new_traffic(self, monkeypatch):
        # Review finding (Greptile P1 / hex-security): eviction must not depend
        # on a later acquire()/store() — a drained group's session would pin a
        # duckgres worker indefinitely. The sweeper calls _evict_stale on a
        # timer; this exercises it directly with a controlled clock.
        conn1 = MagicMock()
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor.time",
            MagicMock(monotonic=lambda: clock["now"]),
        )
        with self._connect_patch() as mock_connect:
            mock_connect.return_value = conn1
            process_batch(_make_batch(batch_index=1))

        clock["now"] += 91.0
        _session_cache._evict_stale()

        conn1.close.assert_called_once()

    def test_store_starts_the_sweeper_thread_once(self):
        with self._connect_patch() as mock_connect:
            mock_connect.return_value = MagicMock()
            process_batch(_make_batch(batch_index=1))
            process_batch(_make_batch(batch_index=2))

        assert _session_cache._sweeper_started is True

    def test_org_change_invalidates_the_cached_session(self):
        # Review finding (veria): the cache key must include the org so a team
        # transferred between organizations can never keep writing through the
        # previous org's authenticated connection.
        conn1, conn2 = MagicMock(), MagicMock()
        with self._connect_patch() as mock_connect:
            mock_connect.side_effect = [conn1, conn2]
            process_batch(_make_batch(batch_index=1))
            self.mock_team.objects.only.return_value.get.return_value.organization_id = "org-b"
            process_batch(_make_batch(batch_index=2))

        assert mock_connect.call_count == 2

    def test_per_org_session_cap_evicts_the_oldest_entry(self):
        # hex-security follow-up: retained sessions must never accumulate past
        # a small per-org bound, even across many sequentially drained groups —
        # each cached session pins a duckgres worker.
        conns = [MagicMock() for _ in range(5)]
        with self._connect_patch() as mock_connect:
            mock_connect.side_effect = conns
            for i in range(5):
                process_batch(_make_batch(schema_id=f"schema-{i}"))

        assert len(_session_cache._entries) == 4
        conns[0].close.assert_called_once()
        for c in conns[1:]:
            c.close.assert_not_called()

    def test_cache_miss_resolves_the_team_once(self):
        # greptile follow-up: org resolution feeds both the cache key and the
        # connection config — one ORM lookup per batch, not two.
        with self._connect_patch() as mock_connect:
            mock_connect.return_value = MagicMock()
            process_batch(_make_batch(batch_index=1))

        assert self.mock_team.objects.only.return_value.get.call_count == 1


def _existence_conn(exists: bool):
    """A mock connection whose LIMIT-0 probe reports existence: it succeeds when
    the table exists, and raises duckgres's XX000 "... does not exist" when not."""
    conn = MagicMock()
    if not exists:
        conn.execute.side_effect = psycopg.errors.InternalError_(
            "flight execute: ... Catalog Error: Table with name t does not exist!"
        )
    return conn


class TestTableExistsProbeAndCache:
    """The existence check the sink runs every non-first batch: a cheap
    single-table LIMIT-0 probe (the whole-catalog information_schema check cost
    ~48s under concurrent snapshot commits, prod 2026-07), cached per connection."""

    def test_probe_succeeds_means_exists(self):
        assert _table_exists(_existence_conn(True), "s", "t") is True

    def test_probe_not_found_means_absent(self):
        assert _table_exists(_existence_conn(False), "s", "t") is False

    def test_other_error_propagates_not_treated_as_absent(self):
        # A transient failure must NOT be read as "table absent" (that would pick
        # the create path); only DuckDB's table-missing message means absent.
        conn = MagicMock()
        conn.execute.side_effect = psycopg.errors.InternalError_("flight execute: rpc error: Unavailable")
        with pytest.raises(psycopg.Error):
            _table_exists(conn, "s", "t")

    def test_missing_schema_error_propagates_not_treated_as_table_absent(self):
        # A bare "does not exist" match would swallow a missing schema/catalog/
        # secret and wrongly pick the create path; only "Table with name ..." is
        # absent. (Greptile P1.)
        conn = MagicMock()
        conn.execute.side_effect = psycopg.errors.InternalError_(
            "flight execute: ... Catalog Error: Schema with name s does not exist!"
        )
        with pytest.raises(psycopg.Error):
            _table_exists(conn, "s", "t")

    def test_second_check_on_same_connection_skips_the_probe(self):
        conn = _existence_conn(True)
        assert _table_exists(conn, "posthog_data_imports_team_1", "customers") is True
        assert _table_exists(conn, "posthog_data_imports_team_1", "customers") is True
        assert conn.execute.call_count == 1  # probed once despite two checks

    def test_distinct_tables_each_probe_once(self):
        conn = _existence_conn(True)
        _table_exists(conn, "s", "a")
        _table_exists(conn, "s", "b")
        _table_exists(conn, "s", "a")
        assert conn.execute.call_count == 2

    def test_separate_connections_do_not_share_the_cache(self):
        c1, c2 = _existence_conn(True), _existence_conn(True)
        _table_exists(c1, "s", "t")
        _table_exists(c2, "s", "t")
        assert c1.execute.call_count == 1
        assert c2.execute.call_count == 1

    def test_absent_table_is_not_cached(self):
        # A negative must be re-checked: the table may be created between batches
        # (the create path), so caching "does not exist" would wrongly skip a
        # later insert/merge onto the now-existing table.
        conn = _existence_conn(False)
        assert _table_exists(conn, "s", "t") is False
        assert _table_exists(conn, "s", "t") is False
        assert conn.execute.call_count == 2
