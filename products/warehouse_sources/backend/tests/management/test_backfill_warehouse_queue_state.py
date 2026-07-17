from collections.abc import Generator
from io import StringIO
from typing import Any

import pytest
from unittest.mock import patch

from django.core.management import call_command

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    STATUS_TABLE,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.test_jobs_db import (
    _BATCH_DEFAULTS,
    _ensure_tables,
    _get_test_database_url,
    _truncate_tables,
)

pytestmark = [pytest.mark.django_db]

COMMAND_MODULE = "products.warehouse_sources.backend.management.commands.backfill_warehouse_queue_state"


@pytest.fixture
def queue_conn() -> Generator[psycopg.Connection[Any]]:
    url = _get_test_database_url()
    with psycopg.connect(url, autocommit=True) as conn:
        _ensure_tables(conn)
        _truncate_tables(conn)
        with patch(f"{COMMAND_MODULE}.WAREHOUSE_SOURCES_DATABASE_URL", url):
            yield conn


def _insert_batch(conn: psycopg.Connection[Any], **overrides: Any) -> str:
    import json

    params = {**_BATCH_DEFAULTS, **overrides}
    params["metadata"] = json.dumps(params["metadata"])
    row = conn.execute(
        f"""
        INSERT INTO {BATCH_TABLE} (
            id, team_id, schema_id, source_id, job_id, run_uuid, batch_index, s3_path,
            row_count, byte_size, is_final_batch, total_batches, total_rows, sync_type,
            cumulative_row_count, resource_name, is_resume, is_first_ever_sync, metadata, created_at
        ) VALUES (
            gen_random_uuid(), %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
            %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, %(is_final_batch)s,
            %(total_batches)s, %(total_rows)s, %(sync_type)s, %(cumulative_row_count)s,
            %(resource_name)s, %(is_resume)s, %(is_first_ever_sync)s, %(metadata)s, now()
        ) RETURNING id
        """,
        params,
    ).fetchone()
    assert row is not None
    return str(row[0])


def _insert_raw_status(conn: psycopg.Connection[Any], batch_id: str, state: str, attempt: int = 1) -> None:
    # Deliberately NOT the dual-write: simulates a pre-dual-write pod appending
    # status rows the columns don't reflect.
    conn.execute(
        f"INSERT INTO {STATUS_TABLE} (batch_id, job_state, attempt, created_at) VALUES (%s, %s, %s, now())",
        (batch_id, state, attempt),
    )


def _columns(conn: psycopg.Connection[Any], batch_id: str) -> tuple[str, int, Any]:
    row = conn.execute(
        f"SELECT latest_state, latest_attempt, state_changed_at FROM {BATCH_TABLE} WHERE id = %s",
        (batch_id,),
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def _run(mode: str, *args: str) -> str:
    out = StringIO()
    call_command("backfill_warehouse_queue_state", mode, *args, stdout=out)
    return out.getvalue()


class TestBackfillWarehouseQueueState:
    def test_fill_missing_derives_columns_from_status_log(self, queue_conn):
        drifted = _insert_batch(queue_conn, batch_index=0)
        _insert_raw_status(queue_conn, drifted, "succeeded")
        never_claimed = _insert_batch(queue_conn, batch_index=1)

        _run("fill-missing", "--live-run")

        state, attempt, changed = _columns(queue_conn, drifted)
        assert (state, attempt) == ("succeeded", 1)
        assert changed is not None
        state, _, changed = _columns(queue_conn, never_claimed)
        assert state == "pending"
        assert changed is not None  # visited marker set so the row leaves the backlog

    def test_fill_missing_dry_run_writes_nothing(self, queue_conn):
        bid = _insert_batch(queue_conn)
        _insert_raw_status(queue_conn, bid, "failed")

        out = _run("fill-missing")

        assert "Would fill 1" in out
        assert _columns(queue_conn, bid)[0] == "pending"

    def test_reconcile_fixes_drift_but_respects_newer_dual_writes(self, queue_conn):
        # Drifted: columns stale relative to the log.
        drifted = _insert_batch(queue_conn, batch_index=0)
        _insert_raw_status(queue_conn, drifted, "failed")
        queue_conn.execute(
            f"UPDATE {BATCH_TABLE} SET latest_state = 'executing', state_changed_at = now() - interval '1 hour' WHERE id = %s",
            (drifted,),
        )
        # Newer-than-log columns (a dual-write that raced ahead) must not regress.
        ahead = _insert_batch(queue_conn, batch_index=1)
        _insert_raw_status(queue_conn, ahead, "executing")
        queue_conn.execute(
            f"UPDATE {BATCH_TABLE} SET latest_state = 'succeeded', latest_attempt = 1, state_changed_at = now() + interval '1 minute' WHERE id = %s",
            (ahead,),
        )

        _run("reconcile", "--live-run")

        assert _columns(queue_conn, drifted)[0] == "failed"
        assert _columns(queue_conn, ahead)[0] == "succeeded"

    def test_audit_counts_mismatches_without_writing(self, queue_conn):
        bid = _insert_batch(queue_conn)
        _insert_raw_status(queue_conn, bid, "succeeded")

        out = _run("audit")

        assert "Mismatched rows: 1" in out
        assert _columns(queue_conn, bid)[0] == "pending"
