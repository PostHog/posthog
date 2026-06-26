import tempfile
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, Mock, patch

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import (
    DuckgresColumn,
    _ensure_duckgres_apply_table,
    _insert_batch,
    _mark_duckgres_batch_applied,
    _merge_batch,
    _plan_batch_operation,
    _process_batch,
    _version_keys,
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

    _insert_batch(conn, "warehouse", "customers", "s3://bucket/path", ["id", "email"])

    query = conn.execute.call_args.args[0]
    assert "SELECT *" not in repr(query)
    assert conn.execute.call_args.args[1] == ["s3://bucket/path"]


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


# --- version-aware merge (webhook latest-state-wins fix) ---
#
# Event-streamed sources emit several rows per id (queued -> in_progress -> completed). Without a
# version key the merge keeps whichever event landed last in batch/file order, which froze rows
# pre-completion. These run the real SQL `_merge_batch` builds against DuckDB (the duckgres dialect)
# to prove the latest state wins regardless of arrival order.

_JOB_COLUMNS = ["id", "status", "completed_at", "started_at", "created_at"]
_JOB_VERSION_KEYS = ["completed_at", "started_at", "created_at"]
# Pin the schema so an all-NULL timestamp column doesn't get inferred as INT and break the
# string merge — the real warehouse rows store these GitHub timestamps as strings.
_JOB_ARROW_SCHEMA = pa.schema(
    [
        ("id", pa.int64()),
        ("status", pa.string()),
        ("completed_at", pa.string()),
        ("started_at", pa.string()),
        ("created_at", pa.string()),
    ]
)


class _QueryCapturingConn:
    """Captures the query `_merge_batch` composes so the test can run it on a real DuckDB session."""

    def __init__(self) -> None:
        self.query: Any = None

    def execute(self, query: Any, params: Any = None) -> None:
        self.query = query


def _write_parquet(rows: list[dict[str, Any]], columns: list[str], path: Path) -> None:
    table = pa.table({col: [row.get(col) for row in rows] for col in columns}, schema=_JOB_ARROW_SCHEMA)
    pq.write_table(table, path)


def _run_merge_on_duckdb(
    target_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    *,
    version_keys: list[str] | None,
) -> dict[int, dict[str, Any]]:
    # `target_rows` model the rows a prior batch already merged in; `source_rows` are the incoming
    # batch — so the same helper exercises both within-batch dedup and cross-batch overwrite/guard.
    with tempfile.TemporaryDirectory() as tmp:
        target_parquet = Path(tmp) / "target.parquet"
        source_parquet = Path(tmp) / "source.parquet"
        _write_parquet(target_rows, _JOB_COLUMNS, target_parquet)
        _write_parquet(source_rows, _JOB_COLUMNS, source_parquet)

        duck = duckdb.connect()
        duck.execute(f"CREATE TABLE main.jobs AS SELECT * FROM read_parquet('{target_parquet}')")

        capturing = _QueryCapturingConn()
        _merge_batch(capturing, "main", "jobs", str(source_parquet), _JOB_COLUMNS, ["id"], version_keys)
        # `_merge_batch` leaves the parquet path as a `%s` bind param; inline it to run on DuckDB.
        rendered = capturing.query.as_string(None).replace("%s", f"'{source_parquet}'")
        duck.execute(rendered)

        rows = duck.execute(f"SELECT {', '.join(_JOB_COLUMNS)} FROM main.jobs").fetchall()
        return {int(row[0]): dict(zip(_JOB_COLUMNS, row)) for row in rows}


def _status(result: dict[int, dict[str, Any]]) -> dict[int, str]:
    return {id: row["status"] for id, row in result.items()}


def _job(
    id: int, status: str, *, created: str, started: str | None = None, completed: str | None = None
) -> dict[str, Any]:
    return {"id": id, "status": status, "created_at": created, "started_at": started, "completed_at": completed}


@pytest.mark.parametrize(
    "target_rows, source_rows, expected",
    [
        # Whole lifecycle in one batch, deliberately not completed-last: QUALIFY must still keep completed.
        (
            [_job(1, "in_progress", created="t0", started="t1")],
            [
                _job(1, "queued", created="t0"),
                _job(1, "completed", created="t0", started="t1", completed="t2"),
                _job(1, "in_progress", created="t0", started="t1"),
            ],
            {1: "completed"},
        ),
        # A late/out-of-order in_progress event must not roll a completed row back.
        (
            [_job(1, "completed", created="t0", started="t1", completed="t2")],
            [_job(1, "in_progress", created="t0", started="t3")],
            {1: "completed"},
        ),
        # Unseen id is inserted, existing rows untouched.
        (
            [_job(1, "completed", created="t0", started="t1", completed="t2")],
            [_job(2, "completed", created="u0", started="u1", completed="u2")],
            {1: "completed", 2: "completed"},
        ),
    ],
    ids=["completed_wins_within_batch", "no_rollback_to_stale", "new_id_inserted"],
)
def test_version_aware_merge_keeps_latest_state(
    target_rows: list[dict[str, Any]], source_rows: list[dict[str, Any]], expected: dict[int, str]
) -> None:
    result = _run_merge_on_duckdb(target_rows, source_rows, version_keys=_JOB_VERSION_KEYS)
    assert _status(result) == expected


@pytest.mark.parametrize(
    "incoming_started, expected_started",
    [
        ("t3", "t5"),  # stale event arriving in a later batch must NOT roll started_at back
        ("t9", "t9"),  # genuinely newer in_progress event advances the row
    ],
    ids=["stale_intermediate_ignored", "newer_intermediate_applies"],
)
def test_version_guard_protects_intermediate_fields_across_batches(
    incoming_started: str, expected_started: str
) -> None:
    # Both rows are pre-completion (completed_at NULL), so a terminal-only guard would let either
    # win — the full version-tuple comparison is what keeps the newer started_at.
    result = _run_merge_on_duckdb(
        [_job(1, "in_progress", created="t0", started="t5")],
        [_job(1, "in_progress", created="t0", started=incoming_started)],
        version_keys=_JOB_VERSION_KEYS,
    )
    assert result[1]["started_at"] == expected_started


def test_merge_without_version_keys_still_upserts() -> None:
    # Sources that declare no version key keep the legacy unconditional upsert.
    result = _run_merge_on_duckdb(
        [_job(1, "old", created="t0")],
        [_job(1, "new", created="t0", completed="t2")],
        version_keys=None,
    )
    assert _status(result) == {1: "new"}


def test_version_keys_reads_batch_metadata() -> None:
    assert _version_keys(_make_batch(metadata={"version_keys": ["updated_at"]})) == ["updated_at"]
    assert _version_keys(_make_batch(metadata={})) is None


def test_plan_batch_operation_threads_version_keys_into_merge() -> None:
    batch = _make_batch(metadata={"primary_keys": ["id"], "version_keys": ["completed_at"]})
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
        return_value=True,
    ):
        operation = _plan_batch_operation(_make_conn(), batch, duckgres_schema="s", duckgres_table="t")
    assert operation.kind == "merge"
    assert operation.primary_keys == ["id"]
    assert operation.version_keys == ["completed_at"]
