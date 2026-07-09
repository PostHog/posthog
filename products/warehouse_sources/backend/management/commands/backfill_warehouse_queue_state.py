"""Backfill and verify the denormalized state columns on sourcebatch.

The dual-write CTEs in jobs_db keep latest_state/latest_attempt/state_changed_at
in step with sourcebatchstatus for new writes; this command brings pre-existing
rows up to date (fill-missing), repairs drift (reconcile), and measures it
(audit). sourcebatchstatus is the source of truth throughout.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
    latest_status_lateral,
)

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 5000

# Truth per batch: its latest status row, or 'pending' when none exists. For
# never-claimed rows state_changed_at is set to the batch's own created_at so
# the NULL "never visited" marker clears and retry-backoff math stays sane.
_TRUTH_SELECT = f"""
    SELECT
        b.id,
        b.created_at,
        COALESCE(s.job_state, 'pending') AS expected_state,
        COALESCE(s.attempt, 0)::smallint AS expected_attempt,
        COALESCE(s.created_at, b.created_at) AS expected_changed_at
    FROM {BATCH_TABLE} b
    {latest_status_lateral("b", "s")}
    WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
"""

FILL_MISSING_SQL = f"""
    WITH truth AS (
        {_TRUTH_SELECT}
          AND b.state_changed_at IS NULL
        LIMIT %(batch_size)s
    )
    UPDATE {BATCH_TABLE} b
    SET latest_state = t.expected_state,
        latest_attempt = t.expected_attempt,
        state_changed_at = t.expected_changed_at
    FROM truth t
    WHERE b.id = t.id
      AND b.created_at = t.created_at
      AND b.state_changed_at IS NULL
"""

RECONCILE_SQL = f"""
    WITH truth AS (
        {_TRUTH_SELECT}
          AND (b.latest_state, b.latest_attempt)
              IS DISTINCT FROM (COALESCE(s.job_state, 'pending'), COALESCE(s.attempt, 0))
        LIMIT %(batch_size)s
    )
    UPDATE {BATCH_TABLE} b
    SET latest_state = t.expected_state,
        latest_attempt = t.expected_attempt,
        state_changed_at = t.expected_changed_at
    FROM truth t
    WHERE b.id = t.id
      AND b.created_at = t.created_at
      AND (b.latest_state, b.latest_attempt) IS DISTINCT FROM (t.expected_state, t.expected_attempt)
      AND (b.state_changed_at IS NULL OR b.state_changed_at <= t.expected_changed_at)
"""

AUDIT_SQL = f"""
    SELECT
        COALESCE(s.job_state, 'pending') AS expected_state,
        b.latest_state AS actual_state,
        count(*) AS mismatches
    FROM {BATCH_TABLE} b
    {latest_status_lateral("b", "s")}
    WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
      AND (b.latest_state, b.latest_attempt)
          IS DISTINCT FROM (COALESCE(s.job_state, 'pending'), COALESCE(s.attempt, 0))
    GROUP BY 1, 2
    ORDER BY 3 DESC
"""

COUNT_MISSING_SQL = f"""
    SELECT count(*) FROM {BATCH_TABLE} b
    WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
      AND b.state_changed_at IS NULL
"""


class Command(BaseCommand):
    help = (
        "Backfill (fill-missing), repair (reconcile), or measure (audit) the denormalized "
        "sourcebatch state columns against the sourcebatchstatus log. Writes need --live-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["fill-missing", "reconcile", "audit"])
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default reports only)")
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
        parser.add_argument(
            "--max-batches", type=int, default=0, help="Stop after N update batches (0 = run to completion)"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        mode: str = options["mode"]
        with psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            if mode == "audit":
                self._audit(conn)
                return
            if not options["live_run"]:
                self._dry_run_report(conn, mode)
                return
            self._run_updates(
                conn,
                mode=mode,
                sql=FILL_MISSING_SQL if mode == "fill-missing" else RECONCILE_SQL,
                batch_size=options["batch_size"],
                max_batches=options["max_batches"],
            )

    def _audit(self, conn: psycopg.Connection[Any]) -> None:
        rows = conn.execute(AUDIT_SQL).fetchall()
        total = sum(r[2] for r in rows)
        for expected, actual, count in rows:
            self.stdout.write(f"  expected={expected} actual={actual}: {count}")
        missing = conn.execute(COUNT_MISSING_SQL).fetchone()
        self.stdout.write(
            f"Mismatched rows: {total}. Never dual-written (state_changed_at IS NULL): {missing[0] if missing else 0}."
        )

    def _dry_run_report(self, conn: psycopg.Connection[Any], mode: str) -> None:
        if mode == "fill-missing":
            row = conn.execute(COUNT_MISSING_SQL).fetchone()
            self.stdout.write(f"Would fill {row[0] if row else 0} row(s). Re-run with --live-run to apply.")
            return
        self._audit(conn)
        self.stdout.write("Re-run with --live-run to repair the mismatches above.")

    def _run_updates(
        self,
        conn: psycopg.Connection[Any],
        *,
        mode: str,
        sql: str,
        batch_size: int,
        max_batches: int,
    ) -> None:
        if batch_size <= 0:
            raise CommandError("--batch-size must be positive")
        total = 0
        batches = 0
        while True:
            updated = conn.execute(sql, {"batch_size": batch_size}).rowcount or 0
            total += updated
            batches += 1
            logger.info("backfill_warehouse_queue_state_batch", mode=mode, batch=batches, updated=updated)
            if updated < batch_size or (max_batches and batches >= max_batches):
                break
        self.stdout.write(self.style.SUCCESS(f"{mode}: updated {total} row(s) in {batches} batch(es)."))
