"""Queue-side writes for the duckgres backfill.

Everything here is idempotent so the reconciler can replay any step after a
crash: pre-apply markers upsert by their natural key, status inserts guard on
the latest-status view, and chunk enqueue keys on (run_uuid, batch_index).
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from products.warehouse_sources.backend.models import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_snapshot import (
    BackfillChunk,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.batch_kind import (
    LIVE_BATCH_SQL_PREDICATE,
    build_backfill_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
    STATUS_TABLE as DELTA_STATUS_TABLE,
)

BACKFILL_JOB_ID = "duckgres-backfill"

# Session advisory-lock namespace that serializes enqueue_chunks per run_uuid.
# Distinct from the batch-claim lock namespace (0x44475300) so the two never
# conflict: (run_uuid, batch_index) has no DB uniqueness guard, so without this
# two pods replaying _reconcile_one for the same run could both pass the
# existing-index check and insert duplicate chunk rows.
BACKFILL_ENQUEUE_LOCK_NAMESPACE = 0x44475301  # "DGS\x01"

# Structured kinds stamped into duckgres status error_response by this module's
# writers (the reconciler dispatches on these, never on message prose).
KIND_COVERED_BY_SNAPSHOT = "covered_by_backfill_snapshot"
KIND_RETIRED_BY_REPLAN = "retired_by_backfill_replan"

REASON_COVERED_BY_SNAPSHOT = "covered by duckgres backfill snapshot"
REASON_RETIRED_BY_REPLAN = "retired by backfill replan"


def backfill_run_uuid(schema_id: str, snapshot_version: int) -> str:
    """Unique per planning attempt: the generation nonce guarantees a replan at
    an unadvanced Delta version still gets a fresh, claimable run."""
    return f"{BACKFILL_JOB_ID}-{schema_id}-v{snapshot_version}-g{uuid.uuid4().hex[:8]}"


def preapply_covered_batches(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    schema_id: str,
    covered_batches: list[tuple[str, int]],
    reason: str,
) -> int:
    """Mark snapshot-contained batches as already applied — skip, never fail.

    Containment proof is per BATCH: the planner reads the pinned Delta snapshot's
    commit metadata and passes every (run_uuid, batch_index) whose commit version
    is <= the snapshot version. Queue timestamps are deliberately not used here;
    they can race the Delta snapshot read.

    "Applied" is the correct verb (not "failed"): a failed batch poisons its
    whole run via the failed-run exclusion, which would drop a mid-flight run's
    later, post-snapshot batches. Pre-applying instead composes with every
    existing gate: the batch stops being claimable (succeeded status), and its
    siblings' head-of-line check sees it applied (apply marker).

    Idempotent: the marker upserts on its natural key and the status insert
    guards on the latest-status view. Final markers are skipped (they never
    carry apply rows; their no-op pass after PRIMED converges them).
    """
    if not covered_batches:
        return 0

    covered_batch_rows = [
        {"run_uuid": run_uuid, "batch_index": batch_index} for run_uuid, batch_index in covered_batches
    ]
    covered_scope = f"""
        FROM {BATCH_TABLE} b
        JOIN (
            SELECT *
            FROM jsonb_to_recordset(%(covered_batches)s::jsonb)
                AS covered(run_uuid text, batch_index int)
        ) covered
            ON covered.run_uuid = b.run_uuid
            AND covered.batch_index = b.batch_index
        JOIN v_latest_source_batch_status ds ON b.id = ds.batch_id
        LEFT JOIN v_latest_source_batch_duckgres_status dgs ON b.id = dgs.batch_id
        WHERE b.team_id = %(team_id)s
            AND b.schema_id = %(schema_id)s
            AND b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND {LIVE_BATCH_SQL_PREDICATE}
            AND b.is_final_batch = false
            AND ds.job_state = 'succeeded'
            AND (dgs.batch_id IS NULL OR dgs.job_state = 'waiting_retry')
    """
    params = {
        "team_id": team_id,
        "schema_id": schema_id,
        "covered_batches": psycopg.types.json.Jsonb(covered_batch_rows),
        "reason": reason,
        "kind": KIND_COVERED_BY_SNAPSHOT,
    }
    with conn.transaction():
        cursor = conn.execute(
            f"""
            INSERT INTO sourcebatchduckgresapply (team_id, schema_id, run_uuid, batch_index, batch_id, row_count)
            SELECT b.team_id, b.schema_id, b.run_uuid, b.batch_index, b.id, b.row_count
            {covered_scope}
            ON CONFLICT (team_id, schema_id, run_uuid, batch_index) DO NOTHING
            """,
            params,
        )
        conn.execute(
            f"""
            INSERT INTO sourcebatchduckgresstatus (batch_id, job_state, attempt, error_response)
            SELECT b.id, 'succeeded', 0, jsonb_build_object('note', %(reason)s::text, 'kind', %(kind)s::text)
            {covered_scope}
            """,
            params,
        )
    return cursor.rowcount or 0


def enqueue_chunks(
    conn: psycopg.Connection[Any],
    schema: ExternalDataSchema,
    run_uuid: str,
    chunks: list[BackfillChunk],
) -> int:
    """Insert the synthetic run, idempotently by (run_uuid, batch_index).

    Each batch row and its pre-succeeded Delta status row commit in ONE
    transaction: a synthetic row visible without 'succeeded' status would be
    claimed by the Delta consumer and loaded into the Delta table.

    (run_uuid, batch_index) has no DB uniqueness guard, so a bare
    read-existing-then-insert races: two pods replaying _reconcile_one for the
    same run could both miss a chunk in ``existing`` and insert it twice. A
    session advisory lock keyed on run_uuid serializes enqueue across pods, so
    the later pod reads a complete ``existing`` set and inserts nothing.
    """
    inserted = 0
    conn.execute(
        "SELECT pg_advisory_lock(%s, hashtext(%s))",
        [BACKFILL_ENQUEUE_LOCK_NAMESPACE, run_uuid],
    )
    try:
        existing = {
            row[0]
            for row in conn.execute(f"SELECT batch_index FROM {BATCH_TABLE} WHERE run_uuid = %s", [run_uuid]).fetchall()
        }
        for chunk in chunks:
            if chunk.index in existing:
                continue
            batch_id = str(uuid.uuid4())
            with conn.transaction():
                conn.execute(
                    f"""
                    INSERT INTO {BATCH_TABLE} (
                        id, team_id, schema_id, source_id, job_id, run_uuid,
                        batch_index, s3_path, row_count, byte_size, is_final_batch,
                        total_batches, total_rows, sync_type, cumulative_row_count,
                        resource_name, is_resume, is_first_ever_sync, metadata
                    ) VALUES (
                        %(id)s, %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
                        %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, false,
                        %(total_batches)s, NULL, 'full_refresh', 0,
                        %(resource_name)s, true, false, %(metadata)s
                    )
                    """,
                    {
                        "id": batch_id,
                        "team_id": schema.team_id,
                        "schema_id": str(schema.id),
                        "source_id": str(schema.source_id),
                        "job_id": BACKFILL_JOB_ID,
                        "run_uuid": run_uuid,
                        "batch_index": chunk.index,
                        "s3_path": chunk.paths[0],
                        "row_count": chunk.row_count,
                        "byte_size": chunk.byte_size,
                        "total_batches": len(chunks),
                        "resource_name": schema.name,
                        "metadata": psycopg.types.json.Jsonb(
                            build_backfill_metadata(chunk_paths=chunk.paths, chunk_count=len(chunks))
                        ),
                    },
                )
                conn.execute(
                    f"INSERT INTO {DELTA_STATUS_TABLE} (batch_id, job_state, attempt) VALUES (%s, 'succeeded', 1)",
                    [batch_id],
                )
            inserted += 1
    finally:
        conn.execute(
            "SELECT pg_advisory_unlock(%s, hashtext(%s))",
            [BACKFILL_ENQUEUE_LOCK_NAMESPACE, run_uuid],
        )
    return inserted


def retire_backfill_run(conn: psycopg.Connection[Any], *, run_uuid: str) -> None:
    """Terminally fail a backfill run's unapplied chunks (operator replan).

    Failing (not pre-applying) is correct HERE: a replanned run's chunks must
    never execute, and the failed-run exclusion is exactly that. The kind is
    deliberately distinct from a live-replace supersession so the reconciler
    can never mistake a replan for a completed refresh.
    """
    conn.execute(
        f"""
        INSERT INTO sourcebatchduckgresstatus (batch_id, job_state, attempt, error_response)
        SELECT b.id, 'failed', 0, jsonb_build_object('error', %(reason)s, 'kind', %(kind)s)
        FROM {BATCH_TABLE} b
        LEFT JOIN sourcebatchduckgresapply a
            ON a.team_id = b.team_id AND a.schema_id = b.schema_id
            AND a.run_uuid = b.run_uuid AND a.batch_index = b.batch_index
        WHERE b.run_uuid = %(run_uuid)s
            AND b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND a.id IS NULL
        """,
        {"run_uuid": run_uuid, "reason": REASON_RETIRED_BY_REPLAN, "kind": KIND_RETIRED_BY_REPLAN},
    )
