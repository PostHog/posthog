"""Backfill primer for the Duckgres batch sink — durable state machine.

Pre-existing incremental/append schemas have history in Delta that the sink's
per-batch stream will never replay. The primer backfills it with bounded
memory and resume-from-checkpoint. This module owns the lifecycle
(DuckgresSinkSchemaState transitions + reconciliation); the moving parts live
in sibling modules:

- backfill_snapshot.py — Delta snapshot resolution and chunk planning (pure).
- backfill_queue.py    — idempotent queue writes (pre-apply, enqueue, retire).
- batch_kind.py        — the canonical live-vs-backfill batch discriminator.

Lifecycle (every transition is a compare-and-swap; the planner runs in every
consumer pod's maintenance tick with no leader election):

  PENDING_BACKFILL --lease CAS--> BACKFILLING(no run)   [lease-reset on crash]
  BACKFILLING(no run) --plan CAS--> BACKFILLING(run)    [the durable plan:
        run_uuid + snapshot_version + chunk_count, written
        BEFORE any queue rows; reconcile replays pre-apply/enqueue from it]
  BACKFILLING(run) --> PRIMED   when chunks_applied == chunk_count (the last
        chunk's apply marker shares the swap's transaction, so full
        application proves the swap), or fast-path via mark_primed after the swap.
  BACKFILLING(run) --> NEEDS_RESYNC  when superseded by a LIVE replace run
        (structured kind): the replace has only reached Delta and may still
        fail in duckgres, so it heals to PRIMED through the resync path below
        rather than flipping PRIMED on a not-yet-complete table.
  *_ --> NEEDS_RESYNC  for unbackfillable tables (deletion vectors) or a
        superseding replace; heals to PRIMED only when a live replace-head run
        has FULLY applied (its final marker reached duckgres-succeeded) —
        replace-head runs bypass the blocked gate precisely so that healing
        path can run.

PRIMED always means "the duckgres table is complete"; nothing else ever sets
it. Containment of pre-applied work is proven per batch from Delta commit
metadata at the pinned snapshot version (see backfill_queue.preapply_covered_batches).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Count
from django.utils import timezone

import psycopg
import structlog
from prometheus_client import Gauge

from posthog.exceptions_capture import capture_exception
from posthog.models import DuckgresSinkSchemaState

from products.warehouse_sources.backend.models import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_queue import (
    BACKFILL_JOB_ID,
    REASON_COVERED_BY_SNAPSHOT,
    backfill_run_uuid,
    enqueue_chunks,
    preapply_covered_batches,
    retire_backfill_run,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_snapshot import (
    BackfillUnsupportedError,
    resolve_snapshot_plan,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.batch_kind import (
    LIVE_BATCH_SQL_PREDICATE,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    RETIRE_KIND_SUPERSEDED_BY_REPLACE,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
)

logger = structlog.get_logger(__name__)

MAX_CONCURRENT_BACKFILLS_PER_ORG = 3  # best-effort across pods (see _plan_pending)
# Global ceiling on backfills in flight across ALL orgs. Backfill chunks and live
# batches share the consumer's group-concurrency pool (BatchConsumerConfig.max_concurrency),
# so this bounds how much of the duckgres worker budget backfills may consume and
# reserves headroom for live application. Tune to (worker ceiling − live headroom);
# keep <= max_concurrency. The per-org cap then keeps one org from eating the whole budget.
MAX_CONCURRENT_BACKFILLS_GLOBAL = 5
# A claim that never produced a durable run plan within this window is
# considered crashed and is returned to PENDING by the reconciler. Planning is
# metadata-only (Delta log read + row inserts), so minutes of lease are ample.
PLANNING_LEASE_SECONDS = 900

BACKFILL_SCHEMAS_GAUGE = Gauge(
    "duckgres_backfill_schemas",
    "Duckgres sink schemas per backfill lifecycle state",
    labelnames=["state"],
    multiprocess_mode="livemax",
)

__all__ = [
    "BACKFILL_JOB_ID",
    "BackfillUnsupportedError",
    "backfill_run_uuid",
    "blocked_schema_ids",
    "mark_primed",
    "replan_backfill",
    "run_backfill_planner",
    "sink_eligible_schema_ids",
]


def run_backfill_planner(team_ids: list[int] | None) -> None:
    """One planner pass: bootstrap state rows, reconcile in-flight, plan pending.

    Per-schema failures are isolated; called from the consumer's maintenance
    tick (sync_to_async, thread_sensitive=False).
    """
    close_old_connections()
    if team_ids is not None and not team_ids:
        return

    _bootstrap_state_rows(team_ids)
    _reconcile(team_ids)
    _plan_pending(team_ids)
    _emit_state_gauge()


def blocked_schema_ids(team_ids: list[int] | None) -> list[str]:
    """Schemas whose live batches the sink must not apply yet.

    A schema is blocked unless it has a PRIMED state row — including schemas
    with no row at all, so there is no window between flag-flip and the first
    planner pass where a pre-existing schema's live batches sneak in. The
    queue grants one exception: replace-head runs bypass the block (they
    rebuild the table from scratch, which is always safe and is the healing
    path for NEEDS_RESYNC).
    """
    close_old_connections()
    if team_ids is not None and not team_ids:
        return []

    schemas = ExternalDataSchema.objects.exclude(deleted=True)
    if team_ids is not None:
        schemas = schemas.filter(team_id__in=team_ids)
    primed = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.PRIMED)
    if team_ids is not None:
        primed = primed.filter(team_id__in=team_ids)
    primed_ids = {str(s) for s in primed.values_list("schema_id", flat=True)}
    return [str(sid) for sid in schemas.values_list("id", flat=True) if str(sid) not in primed_ids]


def sink_eligible_schema_ids(team_ids: list[int]) -> list[str]:
    """Schema ids whose (team, source_type) is on warehouse-pipelines-v3.

    The sink claims batches ONLY for these schemas, keeping consumption in
    lockstep with the v3 routing flag — the same gate that decides which source
    types the v3 pipeline produces for and which schemas get primed here. The
    shared queue can hold batches for non-v3 source types (a source_type that
    was v3 during an earlier flag window, or the flag-independent CDC writer);
    without this gate the team-scoped claim applies them anyway, and replace-head
    batches (full_refresh / first-ever incremental) even bypass the unprimed
    block. Enabling a source_type later lets its schemas bootstrap, prime, and
    begin live application through the normal path.

    Evaluated per (team_id, source_type) with a local cache — the same gate
    ``_bootstrap_state_rows`` uses to decide priming, so consumption and priming
    never disagree. Raises on app-DB errors so the caller keeps its previous
    cached set; a transient blip must not silently empty the allow-list.

    Prod only: the consumer calls this with a concrete team list. Dev mode
    (no team filter) is left ungated by the caller.
    """
    close_old_connections()
    if not team_ids:
        return []

    # Lazy import: create_job_model pulls in temporalio.activity + the data
    # warehouse facade, kept off the planner module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (  # noqa: PLC0415 — keeps the heavy temporal/facade deps off the import path
        is_pipeline_v3_enabled,
    )

    schemas = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(team_id__in=team_ids)
        .values("id", "team_id", "source__source_type")
    )
    v3_enabled: dict[tuple[int, str], bool] = {}
    eligible: list[str] = []
    for schema in schemas.iterator(chunk_size=BOOTSTRAP_BATCH_SIZE):
        key = (schema["team_id"], schema["source__source_type"])
        if key not in v3_enabled:
            v3_enabled[key] = is_pipeline_v3_enabled(schema["team_id"], schema["source__source_type"])
        if v3_enabled[key]:
            eligible.append(str(schema["id"]))
    return eligible


def mark_primed(schema_id: str, *, run_uuid: str, chunks_applied: int | None = None) -> None:
    """Fast path called by the processor right after the swap commits.

    CAS from BACKFILLING only — the reconciler is the authoritative healer,
    and a late call must never clobber a state that has since moved on. The
    CAS is also pinned to the run generation: a replan can retire run R1 and
    plan R2 while R1's final chunk is still mid-swap (its duckgres transaction
    cannot be cancelled), and R1's late mark_primed must not flip R2's row —
    that would unblock live batches over a table R2's own swap later replaces,
    silently dropping them.
    """
    updates: dict[str, Any] = {
        "state": DuckgresSinkSchemaState.State.PRIMED,
        "updated_at": timezone.now(),
    }
    if chunks_applied is not None:
        updates["chunks_applied"] = chunks_applied
    DuckgresSinkSchemaState.objects.filter(
        schema_id=schema_id,
        state=DuckgresSinkSchemaState.State.BACKFILLING,
        backfill_run_uuid=run_uuid,
    ).update(**updates)


def replan_backfill(schema_id: str) -> None:
    """Operator entrypoint: retire the current backfill run and re-enter planning.

    The next plan gets a fresh generation nonce, so an unadvanced Delta
    version still yields a new, claimable run.
    """
    state = DuckgresSinkSchemaState.objects.get(schema_id=schema_id)
    if state.backfill_run_uuid:
        with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            retire_backfill_run(conn, run_uuid=state.backfill_run_uuid)
    DuckgresSinkSchemaState.objects.filter(id=state.id).update(
        state=DuckgresSinkSchemaState.State.PENDING_BACKFILL,
        snapshot_version=None,
        plan_cutoff=None,
        backfill_run_uuid=None,
        chunk_count=None,
        chunks_applied=0,
        last_error=None,
        updated_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Bootstrap & planning
# ---------------------------------------------------------------------------


BOOTSTRAP_BATCH_SIZE = 1000


def _bootstrap_state_rows(team_ids: list[int] | None) -> None:
    """Create state rows for enabled teams' schemas that have none.

    Only schemas whose source is on warehouse-pipelines-v3 get a row: the sink
    follows v3 sources only, so priming a non-v3 source would create state the
    consumer never advances (and never primes).

    Straight to PRIMED when no priming is needed:
    - full_refresh: every run's batch 0 replaces the table completely.
    - no Delta table yet: the first sync creates everything.
    - cdc: the sink rejects CDC batches outright; do not block the queue on it.

    Memory-bounded: a single team can own tens of thousands of schemas, so we
    anti-join in Postgres to skip schemas that already have a state row, stream
    the rest with a server-side cursor instead of materializing the whole set,
    and flush in fixed batches so the in-flight list never grows unbounded.
    """
    # Lazy import: create_job_model pulls in temporalio.activity + the data_warehouse
    # facade, which we don't want on the planner module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (  # noqa: PLC0415 — keeps the heavy temporal/facade deps off the import path
        is_pipeline_v3_enabled,
    )

    schemas = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .exclude(id__in=DuckgresSinkSchemaState.objects.values("schema_id"))
        .values("id", "team_id", "sync_type", "table_id", "source__source_type")
    )
    if team_ids is not None:
        schemas = schemas.filter(team_id__in=team_ids)

    # The sink only follows v3 sources (warehouse-pipelines-v3 is evaluated per
    # team+source_type), so only prime schemas the consumer will actually mirror.
    # Memoized per (team_id, source_type) — the flag does a network eval, and a
    # team has only a handful of source types, so this stays cheap even with many schemas.
    v3_enabled: dict[tuple[int, str], bool] = {}

    def _source_is_v3(team_id: int, source_type: str) -> bool:
        key = (team_id, source_type)
        if key not in v3_enabled:
            v3_enabled[key] = is_pipeline_v3_enabled(team_id, source_type)
        return v3_enabled[key]

    created = 0
    to_create: list[DuckgresSinkSchemaState] = []
    for schema in schemas.iterator(chunk_size=BOOTSTRAP_BATCH_SIZE):
        if not _source_is_v3(schema["team_id"], schema["source__source_type"]):
            continue
        needs_backfill = schema["sync_type"] not in ("full_refresh", "cdc", None) and schema["table_id"] is not None
        to_create.append(
            DuckgresSinkSchemaState(
                team_id=schema["team_id"],
                schema_id=schema["id"],
                state=(
                    DuckgresSinkSchemaState.State.PENDING_BACKFILL
                    if needs_backfill
                    else DuckgresSinkSchemaState.State.PRIMED
                ),
            )
        )
        if len(to_create) >= BOOTSTRAP_BATCH_SIZE:
            DuckgresSinkSchemaState.objects.bulk_create(to_create, ignore_conflicts=True)
            created += len(to_create)
            to_create = []

    if to_create:
        DuckgresSinkSchemaState.objects.bulk_create(to_create, ignore_conflicts=True)
        created += len(to_create)
    if created:
        logger.info("duckgres_backfill_bootstrapped", created=created)


def _plan_pending(team_ids: list[int] | None) -> None:
    pending = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.PENDING_BACKFILL)
    if team_ids is not None:
        pending = pending.filter(team_id__in=team_ids)

    # Oldest-touched first so a failing schema cannot starve the rest of the slice.
    for state in pending.select_related("team").order_by("updated_at")[:50]:
        # Global ceiling: backfills share the consumer worker pool with live
        # application, so once the global budget is full no org may claim —
        # stop scanning this tick. Re-evaluated each iteration since earlier
        # iterations may have claimed slots.
        if _global_at_capacity():
            break

        org_id = state.team.organization_id
        if _org_at_capacity(org_id):
            continue

        # Lease claim: exactly one pod proceeds past this line per schema.
        claimed = DuckgresSinkSchemaState.objects.filter(
            id=state.id, state=DuckgresSinkSchemaState.State.PENDING_BACKFILL
        ).update(state=DuckgresSinkSchemaState.State.BACKFILLING, updated_at=timezone.now())
        if not claimed:
            continue

        # Re-check both caps after winning the claim; the pre-checks raced against
        # other pods. Excluding self (now BACKFILLING), revert if either the org or
        # the global budget is already at capacity. (Still best-effort across pods —
        # a transient over-the-cap backfill is wasteful, not incorrect.)
        if _org_at_capacity(org_id, exclude_id=state.id) or _global_at_capacity(exclude_id=state.id):
            _revert_to_pending(state.id)
            continue

        try:
            _plan_one(state)
        except BackfillUnsupportedError as e:
            DuckgresSinkSchemaState.objects.filter(id=state.id).update(
                state=DuckgresSinkSchemaState.State.NEEDS_RESYNC,
                last_error=str(e)[:2000],
                updated_at=timezone.now(),
            )
            logger.warning("duckgres_backfill_unsupported", schema_id=str(state.schema_id), error=str(e))
        except Exception as e:
            logger.exception("duckgres_backfill_plan_failed", schema_id=str(state.schema_id))
            capture_exception(e)
            _revert_to_pending(state.id, error=str(e)[:2000])


def _org_at_capacity(org_id: Any, *, exclude_id: Any = None) -> bool:
    """Is this org at its per-org backfill cap? Pass exclude_id to ignore the
    just-claimed row when re-checking after a claim."""
    qs = DuckgresSinkSchemaState.objects.filter(
        state=DuckgresSinkSchemaState.State.BACKFILLING,
        team__organization_id=org_id,
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.count() >= MAX_CONCURRENT_BACKFILLS_PER_ORG


def _global_at_capacity(*, exclude_id: Any = None) -> bool:
    """Is the global backfill budget (across all orgs) full? Counts every
    BACKFILLING row, since all backfills draw from one shared worker pool."""
    qs = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.BACKFILLING)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.count() >= MAX_CONCURRENT_BACKFILLS_GLOBAL


def _revert_to_pending(state_id: Any, error: str | None = None) -> None:
    updates: dict[str, Any] = {
        "state": DuckgresSinkSchemaState.State.PENDING_BACKFILL,
        "updated_at": timezone.now(),
    }
    if error is not None:
        updates["last_error"] = error
    DuckgresSinkSchemaState.objects.filter(
        id=state_id, state=DuckgresSinkSchemaState.State.BACKFILLING, backfill_run_uuid__isnull=True
    ).update(**updates)


def _has_inflight_replace_run(conn: psycopg.Connection[Any], *, team_id: int, schema_id: str) -> bool:
    """A replace-head live run that Delta accepted but duckgres has not finished.

    Batch 0 replace-shaped and delta-succeeded, with no terminal Delta failure,
    duckgres-succeeded final marker (completion), or duckgres-failed batch for
    the run. Planning must wait these out: the snapshot would cover the run's
    head and orphan its tail (see the guard in _plan_one).
    """
    row = conn.execute(
        f"""
        SELECT 1
        FROM {BATCH_TABLE} h
        JOIN v_latest_source_batch_status hds ON hds.batch_id = h.id
        WHERE h.team_id = %(team_id)s
            AND h.schema_id = %(schema_id)s
            AND h.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND h.batch_index = 0
            AND h.is_final_batch = false
            AND h.is_resume = false
            AND (h.sync_type = 'full_refresh' OR (h.sync_type = 'incremental' AND h.is_first_ever_sync))
            AND hds.job_state = 'succeeded'
            AND NOT EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} x
                JOIN v_latest_source_batch_status xds ON xds.batch_id = x.id
                WHERE x.run_uuid = h.run_uuid
                    AND x.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND xds.job_state = 'failed'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} f
                JOIN v_latest_source_batch_duckgres_status fdgs ON fdgs.batch_id = f.id
                WHERE f.run_uuid = h.run_uuid
                    AND f.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND f.is_final_batch = true
                    AND fdgs.job_state = 'succeeded'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} x
                JOIN v_latest_source_batch_duckgres_status xdgs ON xdgs.batch_id = x.id
                WHERE x.run_uuid = h.run_uuid
                    AND x.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND xdgs.job_state = 'failed'
            )
        LIMIT 1
        """,
        {"team_id": team_id, "schema_id": schema_id},
    ).fetchone()
    return row is not None


def _plan_one(state: DuckgresSinkSchemaState) -> None:
    """Runs only on the pod that won the lease claim.

    Ordering is crash-safety-critical:
    1. resolve the snapshot (no side effects),
    2. CAS the durable run plan onto the state row — the real claim,
    3. pre-apply covered batches, 4. enqueue chunks.
    A crash after step 2 is healed by _reconcile_one (replay 3-4 from the
    stored plan); a crash before it is healed by the planning lease.
    """
    schema = ExternalDataSchema.objects.select_related("source", "team").get(id=state.schema_id)

    with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
        if _has_inflight_replace_run(conn, team_id=schema.team_id, schema_id=str(state.schema_id)):
            # Planning now would pin a snapshot mid-run and pre-apply the
            # replace run's head: its post-snapshot tail would then apply into
            # the doomed pre-swap table (the replace-head gate bypass admits
            # it), and the swap would silently drop those rows while their
            # apply markers prevent any re-apply. Defer until the run reaches
            # a terminal duckgres state; the planner retries every tick.
            logger.info(
                "duckgres_backfill_plan_deferred_for_inflight_replace",
                schema_id=str(state.schema_id),
                team_id=schema.team_id,
            )
            return

        plan = resolve_snapshot_plan(schema)
        snapshot_version = plan.snapshot_version
        chunks = plan.chunks
        if not chunks:
            # Empty Delta table: nothing to prime.
            DuckgresSinkSchemaState.objects.filter(id=state.id).update(
                state=DuckgresSinkSchemaState.State.PRIMED, updated_at=timezone.now()
            )
            return

        run_uuid = backfill_run_uuid(str(state.schema_id), snapshot_version)

        # Durable plan claim: only one pod can attach a run to this state row.
        planned = DuckgresSinkSchemaState.objects.filter(
            id=state.id,
            state=DuckgresSinkSchemaState.State.BACKFILLING,
            backfill_run_uuid__isnull=True,
        ).update(
            snapshot_version=snapshot_version,
            plan_cutoff=None,
            backfill_run_uuid=run_uuid,
            chunk_count=len(chunks),
            chunks_applied=0,
            last_error=None,
            updated_at=timezone.now(),
        )
        if not planned:
            return

        preapplied = preapply_covered_batches(
            conn,
            team_id=schema.team_id,
            schema_id=str(state.schema_id),
            covered_batches=plan.covered_batches,
            reason=f"{REASON_COVERED_BY_SNAPSHOT} v{snapshot_version}",
        )
        inserted = enqueue_chunks(conn, schema, run_uuid, chunks)

    logger.info(
        "duckgres_backfill_planned",
        schema_id=str(state.schema_id),
        team_id=schema.team_id,
        run_uuid=run_uuid,
        snapshot_version=snapshot_version,
        chunk_count=len(chunks),
        inserted=inserted,
        preapplied_covered_batches=preapplied,
        total_bytes=sum(c.byte_size for c in chunks),
    )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _reconcile(team_ids: list[int] | None) -> None:
    """Heal and progress every non-terminal state. Authoritative for PRIMED."""
    # Half-claimed rows (crash between the lease CAS and the plan CAS) carry
    # no run plan; after the lease they return to PENDING for a fresh attempt.
    lease_deadline = timezone.now() - timedelta(seconds=PLANNING_LEASE_SECONDS)
    stale = DuckgresSinkSchemaState.objects.filter(
        state=DuckgresSinkSchemaState.State.BACKFILLING,
        backfill_run_uuid__isnull=True,
        updated_at__lt=lease_deadline,
    )
    if team_ids is not None:
        stale = stale.filter(team_id__in=team_ids)
    reset = stale.update(state=DuckgresSinkSchemaState.State.PENDING_BACKFILL, updated_at=timezone.now())
    if reset:
        logger.warning("duckgres_backfill_stale_claims_reset", count=reset)

    backfilling = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.BACKFILLING)
    needs_resync = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.NEEDS_RESYNC)
    if team_ids is not None:
        backfilling = backfilling.filter(team_id__in=team_ids)
        needs_resync = needs_resync.filter(team_id__in=team_ids)
    rows = [s for s in backfilling if s.backfill_run_uuid]
    resync_rows = list(needs_resync)
    if not rows and not resync_rows:
        return

    with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
        for state in rows:
            try:
                _reconcile_one(conn, state)
            except Exception as e:
                logger.exception("duckgres_backfill_reconcile_failed", schema_id=str(state.schema_id))
                capture_exception(e)
        for state in resync_rows:
            try:
                _reconcile_needs_resync(conn, state)
            except Exception as e:
                logger.exception("duckgres_backfill_resync_check_failed", schema_id=str(state.schema_id))
                capture_exception(e)


def _reconcile_one(conn: psycopg.Connection[Any], state: DuckgresSinkSchemaState) -> None:
    run_uuid = state.backfill_run_uuid
    applied_row = conn.execute(
        "SELECT count(DISTINCT batch_index) FROM sourcebatchduckgresapply WHERE run_uuid = %s", [run_uuid]
    ).fetchone()
    applied = int(applied_row[0]) if applied_row else 0

    if state.chunk_count and applied >= state.chunk_count:
        # Full application proves the swap committed (the last chunk's apply
        # marker shares the swap's transaction). CAS so a stale pass can never
        # resurrect a state another pod already advanced — pinned to the run
        # the applied-count evidence was gathered for, so a replan that swapped
        # generations mid-pass cannot be promoted on the old run's counts.
        DuckgresSinkSchemaState.objects.filter(
            id=state.id,
            state=DuckgresSinkSchemaState.State.BACKFILLING,
            backfill_run_uuid=run_uuid,
        ).update(
            state=DuckgresSinkSchemaState.State.PRIMED,
            chunks_applied=applied,
            updated_at=timezone.now(),
        )
        return

    failed = conn.execute(
        f"""
        SELECT dgs.error_response->>'error', dgs.error_response->>'kind'
        FROM v_latest_source_batch_duckgres_status dgs
        JOIN {BATCH_TABLE} b ON b.id = dgs.batch_id
        WHERE b.run_uuid = %s AND dgs.job_state = 'failed'
        LIMIT 1
        """,
        [run_uuid],
    ).fetchone()

    if failed is not None:
        reason = failed[0] or ""
        kind = failed[1]
        if kind == RETIRE_KIND_SUPERSEDED_BY_REPLACE:
            # A LIVE replace run retired the backfill. The replace rebuilds the
            # table completely, but at this point it has only reached Delta — it
            # may still fail in duckgres. Flipping straight to PRIMED here would
            # unblock live batches over a stale/incomplete table if the replace
            # later exhausts retries. Park in NEEDS_RESYNC so the resync path
            # promotes to PRIMED only once the replace run's final marker reaches
            # duckgres-succeeded (the same completion proof every PRIMED requires).
            DuckgresSinkSchemaState.objects.filter(id=state.id, state=DuckgresSinkSchemaState.State.BACKFILLING).update(
                state=DuckgresSinkSchemaState.State.NEEDS_RESYNC, last_error=None, updated_at=timezone.now()
            )
            logger.info(
                "duckgres_backfill_superseded_by_live_refresh",
                schema_id=str(state.schema_id),
                run_uuid=run_uuid,
            )
        elif state.last_error != reason:
            DuckgresSinkSchemaState.objects.filter(id=state.id).update(
                last_error=reason[:2000], chunks_applied=applied, updated_at=timezone.now()
            )
        return

    # Healthy in-flight run: track progress and replay plan side effects lost
    # to a crash or to 7-day queue retention (apply markers persist 30d, so
    # resume is exact; all replayed writes are idempotent).
    # count DISTINCT batch_index, not count(*): a duplicate chunk row must never
    # inflate the count and mask a genuinely missing index, which would stop the
    # replay from re-enqueueing it.
    present_row = conn.execute(
        f"SELECT count(DISTINCT batch_index) FROM {BATCH_TABLE} WHERE run_uuid = %s", [run_uuid]
    ).fetchone()
    present = int(present_row[0]) if present_row else 0
    if state.chunk_count and present < state.chunk_count and state.snapshot_version is not None:
        schema = ExternalDataSchema.objects.select_related("source").get(id=state.schema_id)
        plan = resolve_snapshot_plan(schema, version=state.snapshot_version)
        preapply_covered_batches(
            conn,
            team_id=state.team_id,
            schema_id=str(state.schema_id),
            covered_batches=plan.covered_batches,
            reason=f"{REASON_COVERED_BY_SNAPSHOT} v{state.snapshot_version}",
        )
        chunks = plan.chunks
        reinserted = enqueue_chunks(conn, schema, str(run_uuid), chunks)
        if reinserted:
            logger.info(
                "duckgres_backfill_reenqueued_dropped_chunks",
                schema_id=str(state.schema_id),
                run_uuid=run_uuid,
                reinserted=reinserted,
            )

    if applied != state.chunks_applied:
        DuckgresSinkSchemaState.objects.filter(id=state.id).update(chunks_applied=applied, updated_at=timezone.now())


def _reconcile_needs_resync(conn: psycopg.Connection[Any], state: DuckgresSinkSchemaState) -> None:
    """Flip NEEDS_RESYNC to PRIMED only when a replace run has FULLY applied.

    Replace-head runs bypass the blocked gate (jobs_db), so a user-triggered
    full refresh can run while the schema is parked. Its final marker reaches
    duckgres-succeeded only after every prior batch applied — that is the
    completion proof, so PRIMED keeps its single meaning: the table is
    complete.
    """
    live_predicate_f = LIVE_BATCH_SQL_PREDICATE.replace("b.", "f.")
    done = conn.execute(
        f"""
        SELECT 1
        FROM {BATCH_TABLE} f
        JOIN v_latest_source_batch_duckgres_status fdgs ON f.id = fdgs.batch_id
        WHERE f.team_id = %(team_id)s
            AND f.schema_id = %(schema_id)s
            AND f.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND {live_predicate_f}
            AND f.is_final_batch = true
            AND fdgs.job_state = 'succeeded'
            AND EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} h
                WHERE h.run_uuid = f.run_uuid
                    AND h.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND h.batch_index = 0
                    AND h.is_final_batch = false
                    AND h.is_resume = false
                    AND (h.sync_type = 'full_refresh' OR (h.sync_type = 'incremental' AND h.is_first_ever_sync))
            )
        LIMIT 1
        """,
        {"team_id": state.team_id, "schema_id": str(state.schema_id)},
    ).fetchone()
    if done is None:
        return

    flipped = DuckgresSinkSchemaState.objects.filter(
        id=state.id, state=DuckgresSinkSchemaState.State.NEEDS_RESYNC
    ).update(state=DuckgresSinkSchemaState.State.PRIMED, last_error=None, updated_at=timezone.now())
    if flipped:
        logger.info("duckgres_backfill_resync_completed", schema_id=str(state.schema_id))


def _emit_state_gauge() -> None:
    counts = dict(DuckgresSinkSchemaState.objects.values_list("state").annotate(n=Count("id")))
    for state_value, _label in DuckgresSinkSchemaState.State.choices:
        BACKFILL_SCHEMAS_GAUGE.labels(state=state_value).set(counts.get(state_value, 0))
