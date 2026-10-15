"""Detection + gating for the automated in-place repartition controller.

Measures per-partition size after a sync (cheap — read from the Delta log) and, when a table's
largest partition outgrows the memory-safe budget, records a `repartition_pending` target on the
schema. The next run's pre-extraction activity performs the rewrite (see `repartition.py` and
`workflow_activities/repartition_table.py`). Everything is observable via PostHog events.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

from django.conf import settings
from django.utils import timezone

import deltalake as deltalake
import posthoganalytics
from dateutil import parser
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_maintenance_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    measure_partition_bytes,
    select_coarsen_target,
    select_repartition_target,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_COARSEN_DECLINE_TOTAL,
    DELTA_REPARTITION_SKIP_TOTAL,
)
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_schema_flag_enabled

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

# Gates pausing a schema's imports while a multi-budget rewrite converges. Off by default:
# repartitioning a table costs us worker time, pausing its imports costs the customer freshness, so
# the second is not a decision the first should make.
WAREHOUSE_REPARTITION_HOLD_FLAG = "data-warehouse-repartition-hold"

# Coarsening gates. The two directions deliberately don't meet: a table is split finer above the budget
# and merged coarser only below an eighth of it, and a coarsen aims at half the budget. So a freshly
# coarsened table has to double before the finer path can claim it, and a freshly split one has to
# shrink eightfold before this path can. Without that gap the controller would hand tables back and
# forth every cooldown.
COARSEN_TRIGGER_DIVISOR = 8
COARSEN_TARGET_DIVISOR = 2
# Below this, fragmentation costs little and a rewrite isn't worth its own risk.
COARSEN_MIN_PARTITIONS = 16
# Let a layout prove itself over a few daily sync cycles before undoing it.
COARSEN_MIN_LAYOUT_AGE_SECONDS = 7 * 24 * 60 * 60
# Longer than the finer path's window: making partitions bigger is the one change that can cause the
# failure it's meant to prevent, so it takes a longer clean run to justify than a split does.
COARSEN_OOM_FREE_DAYS = 14

# Don't repartition the same table more than once a day — the budget has headroom, so a table that
# trips repeatedly should converge over a few daily cycles, not thrash every sync.
REPARTITION_COOLDOWN_SECONDS = 24 * 60 * 60

# Give up (and alert) after this many consecutive failed attempts, at most one per sync run, so a
# permanently-failing table doesn't re-attempt the rewrite on every sync forever.
MAX_REPARTITION_ATTEMPTS = 3

# Reasons `select_repartition_target` gives that describe the table instead of a defect: its data
# carries no key to partition on, or its scheme is already as fine as that scheme goes. The
# controller decided correctly in each case and nobody can act on the result, so these are counted
# on DELTA_REPARTITION_SKIP_TOTAL and reported on `warehouse_repartition_skipped` but never sent to
# error tracking. Every other reason means the schema row disagrees with itself (numerical mode with
# no `partition_size`) or the selector saw a state the caller should have filtered out first
# (`no_partitions`, `within_budget`), which is a bug in us, so it still alerts.
EXPECTED_SKIP_REASONS = frozenset({"unpartitionable_no_keys", "datetime_at_finest_tier", "numerical_cannot_shrink"})


def target_partition_bytes() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_TARGET_PARTITION_BYTES", 500_000_000))


def min_splittable_partition_bytes() -> int:
    """The smallest partition an OOM-triggered split is allowed to produce.

    Derived from the coarsening threshold rather than set independently, so the two directions cannot
    disagree about the same table: anything below this is a layout the coarsening path would want to
    merge back together, and splitting into it would be undoing our own work.

    This is what makes the OOM trigger safe to keep. The OOM signal cannot tell a real kill from a
    deploy or an eviction, so it fires on tables whose partitions were never the problem; requiring the
    result to stay above this floor means the trigger can only act where partition size is a plausible
    cause at all. Splitting below it also multiplies per-partition merge commits, which slows the sync
    that produced the timeouts in the first place.
    """
    return target_partition_bytes() // COARSEN_TRIGGER_DIVISOR


def repartition_oom_threshold() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD", 3))


def repartition_oom_window_days() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS", 7))


def needs_pre_extraction_detection(schema: ExternalDataSchema) -> bool:
    """Whether to read the live on-disk partition sizes to decide if a repartition is needed.

    We deliberately do NOT gate on the recorded `max_partition_bytes`. That value is only refreshed by
    post-load detection, so for a table whose merge OOMs before post-load it goes stale and can sit far
    below the true partition size — precisely the tables this path exists to rescue (e.g. a partition
    that has since grown to many GB while the recorded value still reads a few hundred MB). Instead,
    whenever the table isn't CDC-excluded, we read the live partition sizes from the Delta log each run
    and let `maybe_flag_for_repartition` judge against the real, current size. The cost is one
    metadata-only Delta-log read per sync.
    """
    return schema.sync_type != ExternalDataSchema.SyncType.CDC


MeasurementPhase = Literal["pre_extraction", "post_load"]

# How many earlier jobs the gate below reads to connect a run to the measurement it relies on. A
# longer run of jobs with no rows costs one measurement and then starts a new chain.
MEASUREMENT_CHAIN_LIMIT = 20


def partition_measurement_holds(
    measurement: dict[str, Any] | None, earlier_jobs: Sequence[tuple[str, str, int | None]]
) -> bool:
    """Whether the recorded measurement still describes the table that is on disk now.

    `earlier_jobs` are the schema's jobs before the current one, newest first, as (id, status, rows
    synced). The measurement holds when the job that took it completed, every job after it completed
    with no rows, and the job itself wrote nothing after the measurement: a post-load measurement is
    after its job's last write, and a pre-extraction one needs that job to have synced no rows.

    Only a healthy measurement counts: one where detection had nothing to act on and nothing that
    time alone can change (see `maybe_flag_for_repartition`). A failed or running job anywhere in the
    chain breaks it. That keeps the on-disk read for a table whose merge runs out of memory, because
    such a job never completes.
    """
    if not measurement or measurement.get("healthy") is not True:
        return False
    measured_job_id = measurement.get("job_id")
    for job_id, status, rows_synced in earlier_jobs:
        if status != ExternalDataJob.Status.COMPLETED:
            return False
        if job_id == measured_job_id:
            return measurement.get("phase") == "post_load" or rows_synced == 0
        if rows_synced != 0:
            return False
    return False


def pre_extraction_measurement_is_redundant(schema: ExternalDataSchema, job: ExternalDataJob) -> bool:
    """Whether the pre-extraction activity can skip its read of the Delta log for this run.

    True only when a new read would give the verdict that the last one gave, which was to do
    nothing. No data reached the table since that measurement (see `partition_measurement_holds`),
    so the partition sizes are the same. The inputs that can change with no write are checked here:
    the budget, an operator nomination, and the count of recent OOM kills. The measurement itself is
    healthy only for a table that the coarsening path cannot pick up as time passes.
    """
    if schema.coarsen_requested is not None:
        return False
    measurement = schema.partition_measurement
    if not measurement or measurement.get("healthy") is not True:
        return False
    if measurement.get("budget") != target_partition_bytes():
        return False
    if (
        ExternalDataSchemaOOMEvent.recent_count(schema, days=repartition_oom_window_days())
        >= repartition_oom_threshold()
    ):
        return False
    earlier_jobs = [
        (str(job_id), status, rows_synced)
        for job_id, status, rows_synced in ExternalDataJob.objects.filter(
            pipeline_id=schema.source_id, schema_id=schema.id, created_at__lt=job.created_at
        )
        .order_by("-created_at")
        .values_list("id", "status", "rows_synced")[:MEASUREMENT_CHAIN_LIMIT]
    ]
    return partition_measurement_holds(measurement, earlier_jobs)


def repartition_activity_has_work(schema: ExternalDataSchema) -> bool:
    """Whether the pre-extraction repartition activity would do more than log and return.

    The workflow uses this to skip scheduling the activity, so it must say True whenever the activity
    itself would go past its own fast no-op path: a queued rewrite or staged swap to drive, or a table
    that needs measuring on disk. A pending corruption revive makes the activity stand down before any
    of that, so it is a no-op here too.
    """
    if schema.delta_revive_required is not None:
        return False
    if schema.repartition_swap is not None or schema.repartition_pending is not None:
        return True
    return needs_pre_extraction_detection(schema)


def is_repartition_hold_enabled(schema: ExternalDataSchema) -> bool:
    return is_schema_flag_enabled(schema, WAREHOUSE_REPARTITION_HOLD_FLAG)


def repartition_import_hold_reason(
    schema: ExternalDataSchema, logger: FilteringBoundLogger
) -> Literal["swap_staged", "rewrite_converging"] | None:
    """Why an in-flight repartition holds this schema's import, or None when it does not.

    Two situations hold the import. A staged swap holds it unconditionally, because the table's
    on-disk partition layout is mid-change and merging across that is data corruption, not staleness.
    A converging rewrite holds it only when the schema opted in and its checkpoint is fresh enough to
    be worth waiting for; the flag is checked second so a schema without it never pays for the
    evaluation, and a flag lookup that throws leaves the import running — pausing a customer's
    ingestion is the more expensive way to be wrong.

    Side-effect free, because the scheduled full refresh defers on the same answer. The two must not
    drift: a refresh run skips the repartition activity, so a refresh that proceeds while the import
    is held never wipes the table.
    """
    swap = schema.repartition_swap
    if swap and swap.get("state") == "ready":
        # The rewrite may already have re-bucketed the data in S3 while the schema row still holds the
        # old settings. The merge computes each row's `_ph_partition_key` from those settings and
        # scopes its predicate to `target._ph_partition_key = '<partition>'`, so under that mismatch
        # nothing matches and every fetched row inserts instead of upserting — the whole incremental
        # lookback window duplicated, with the job still reporting Completed. The repartition activity
        # runs ahead of the import on every sync and resolves the marker, so waiting costs one run's
        # freshness. Not behind the hold rollout flag: that flag trades freshness for a rewrite that
        # can finish, and this trades it for not corrupting the table.
        return "swap_staged"

    if not schema.repartition_holds_import:
        return None
    try:
        if not is_repartition_hold_enabled(schema):
            return None
    except Exception:
        logger.warning("Could not evaluate the repartition hold flag; importing", exc_info=True)
        return None
    return "rewrite_converging"


def base_event_props(schema: ExternalDataSchema, source: ExternalDataSource, job_id: str | None) -> dict[str, Any]:
    return {
        "team_id": schema.team_id,
        "schema_id": str(schema.id),
        "source_id": str(schema.source_id),
        "source_type": source.source_type,
        "resource_name": schema.name,
        "job_id": str(job_id) if job_id else None,
        "partition_mode": schema.partition_mode,
        "partition_format": schema.partition_format,
        "partition_count": schema.partition_count,
        "partition_size": schema.partition_size,
    }


def capture_repartition_event(event: str, props: dict[str, Any]) -> None:
    posthoganalytics.capture(distinct_id=get_machine_id(), event=event, properties=props)


def _cooldown_seconds_remaining(schema: ExternalDataSchema) -> float:
    """Seconds until the per-table repartition cooldown expires; 0 when no cooldown is active."""
    last = schema.last_repartition_at
    if not last:
        return 0.0
    try:
        last_dt = parser.parse(last)
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, REPARTITION_COOLDOWN_SECONDS - (timezone.now() - last_dt).total_seconds())


def _seconds_since_last_repartition(schema: ExternalDataSchema) -> float | None:
    """Age of the current layout, or None when this controller never rewrote the table."""
    last = schema.last_repartition_at
    if not last:
        return None
    try:
        last_dt = parser.parse(last)
    except (ValueError, TypeError):
        return None
    return (timezone.now() - last_dt).total_seconds()


async def maybe_flag_for_coarsening(
    schema: ExternalDataSchema,
    source: ExternalDataSource,
    job: ExternalDataJob,
    partition_bytes: dict[str | None, int],
    recent_oom_count: int,
    logger: FilteringBoundLogger,
    *,
    budget: int,
    max_bytes: int,
) -> None:
    """Flag an over-fragmented table to be rebuilt into fewer, larger partitions.

    The counterpart to the finer path, for tables that ended up split far below what memory safety
    needs, most of them by that path reacting to failures partition size never caused. Thousands of
    tiny partitions mean thousands of per-partition merge commits, which is its own way to make a sync
    slow enough to look like the problem the split was meant to solve.

    The gates below split into two kinds, and only one kind is overridable. The *policy* gates decide
    whether a table is worth touching unprompted; an operator who has nominated a table through
    `stage_warehouse_coarsening` has already made that call, so a nomination skips them. The *safety*
    check is `select_coarsen_target`, which measures the live layout and refuses any target that would
    not fit the budget. Nothing overrides that, so a nomination can only ever be a no-op.

    Ordered cheapest first — in-memory shape gates, then the in-memory selector, then the database.
    Post-load detection runs this
    for every within-budget table on every sync, so anything before the selector is fleet-wide cost,
    and most tables that pass the shape gates sit at the coarsest tier where the selector refuses.

    Called from `maybe_flag_for_repartition` on its healthy branch and on its floor-blocked branch
    (OOM history present but partitions too small to split — the over-split backlog's exact state, and
    the only route by which a nominated table there is evaluated). Never raises (the caller swallows).
    """
    measured_partitions = len(partition_bytes)

    def _decline(reason: str) -> None:
        # Every gate below returns silently, so without this "the rollout stalled" and "nothing was
        # eligible" look identical from outside. A counter rather than an event because this runs on
        # every table on every sync.
        DELTA_COARSEN_DECLINE_TOTAL.labels(reason=reason).inc()

    # Never fight a rewrite that is already staged or mid-swap, however the evaluation was prompted.
    if schema.repartition_pending is not None or schema.repartition_swap is not None:
        return

    requested = schema.coarsen_requested
    if requested is None:
        # Below these two the table is not over-fragmented at all, so returning before `_decline`
        # keeps the metric scoped to the population the rollout is about.
        if measured_partitions < COARSEN_MIN_PARTITIONS:
            return
        if max_bytes * COARSEN_TRIGGER_DIVISOR > budget:
            return
        # Cheap short-circuit on the count the caller already has: it covers the split trigger's
        # shorter window, so the authoritative gate over `COARSEN_OOM_FREE_DAYS` is
        # `blocks_coarsening` further down.
        if recent_oom_count > 0:
            return _decline("oom_history_recent")
        layout_age = _seconds_since_last_repartition(schema)
        if layout_age is not None and layout_age < COARSEN_MIN_LAYOUT_AGE_SECONDS:
            return _decline("layout_too_young")

    target, reason = await asyncio.to_thread(
        select_coarsen_target, schema, partition_bytes, budget // COARSEN_TARGET_DIVISOR
    )
    if requested is not None and target is None:
        # Consume a refused nomination now: leaving it set would re-evaluate the same table every sync,
        # and a table the selector refuses today will refuse again until its data changes. A *selected*
        # target keeps the nomination until the pending write lands (below), so a crash between the two
        # writes loses nothing; the leftover marker is then cleared by the next evaluation.
        await asyncio.to_thread(schema.clear_coarsen_requested)

    if target is None:
        # INFO only for an operator, who is waiting on the outcome of a nomination; the automatic path
        # lands here on every sync of every coarsest-tier table, which at INFO would flood the Syncs UI.
        log = logger.ainfo if requested is not None else logger.adebug
        await log(
            f"repartition: no coarser layout applies schema_id={schema.id} reason={reason} "
            f"operator_requested={requested is not None} max_partition_bytes={max_bytes} "
            f"partition_count={measured_partitions}",
            schema_id=str(schema.id),
            reason=reason,
            operator_requested=requested is not None,
            max_partition_bytes=max_bytes,
            partition_count=measured_partitions,
        )
        return _decline(reason)

    if requested is None:
        # Classified, not raw: a nightly restart that kills a hundred unrelated schemas says nothing
        # about any of their merges, and blocking on it would withhold coarsening from all of them.
        if await asyncio.to_thread(ExternalDataSchemaOOMEvent.blocks_coarsening, schema, days=COARSEN_OOM_FREE_DAYS):
            return _decline("oom_within_free_window")

    # Distinct reason for a nominated rewrite, the same way an admin-staged one is distinguishable, so
    # the backlog pass can be tracked separately from what the controller does on its own.
    trigger_reason = "coarsening_requested" if requested is not None else "coarsening"
    pending = {**target.to_dict(), "trigger_reason": trigger_reason, "attempts": 0}
    await asyncio.to_thread(schema.set_repartition_pending, pending)
    if requested is not None:
        # Only after the pending write: consuming the nomination first would lose it to a crash between
        # the two writes, and nothing would ever restore it.
        await asyncio.to_thread(schema.clear_coarsen_requested)

    props = base_event_props(schema, source, str(job.id))
    props.update(
        {
            "max_partition_bytes_before": max_bytes,
            "trigger_reason": trigger_reason,
            "measured_partition_count_before": measured_partitions,
            "partition_mode_after": target.partition_mode or "auto",
            "partition_format_after": target.partition_format,
            "partition_count_after": target.partition_count,
            "partition_size_after": target.partition_size,
        }
    )
    await asyncio.to_thread(capture_repartition_event, "warehouse_repartition_flagged", props)
    await logger.ainfo(
        f"repartition: flagged for coarsening on the next run schema_id={schema.id} "
        f"max_partition_bytes={max_bytes} partition_count={measured_partitions} "
        f"target_mode={target.partition_mode} target_format={target.partition_format} "
        f"target_count={target.partition_count} target_size={target.partition_size}",
        schema_id=str(schema.id),
        max_partition_bytes=max_bytes,
        partition_count=measured_partitions,
        target_mode=target.partition_mode,
        target_format=target.partition_format,
        target_count=target.partition_count,
        target_size=target.partition_size,
    )


async def maybe_flag_for_repartition(
    schema: ExternalDataSchema,
    source: ExternalDataSource,
    job: ExternalDataJob,
    delta_table: deltalake.DeltaTable,
    logger: FilteringBoundLogger,
    *,
    phase: MeasurementPhase = "pre_extraction",
) -> None:
    """Measure partition sizes and, if over budget, record a `repartition_pending` target.

    Always records `max_partition_bytes` for observability (even when the table is in cooldown). The
    rewrite itself happens on the next run. Never raises — detection must not break post-load.

    The measurement is recorded with the job, the `phase` and the verdict, so the next run can tell
    whether it still describes the table (see `partition_measurement_holds`).
    """
    try:
        # A table pending a corruption revive must heal before it's rewritten — flagging it here would
        # re-arm the revive loop after the heal clears the marker. Skip; the healed table is evaluated
        # normally on a later run.
        if schema.delta_revive_required is not None:
            await logger.adebug(
                f"repartition: skipped detection, table pending corruption revive schema_id={schema.id}",
                schema_id=str(schema.id),
            )
            return

        partition_bytes = await asyncio.to_thread(measure_partition_bytes, delta_table)
        if not partition_bytes:
            await logger.adebug(
                f"repartition: skipped, no partition measurements in the delta log schema_id={schema.id}",
                schema_id=str(schema.id),
            )
            return

        max_bytes = max(partition_bytes.values())

        budget = target_partition_bytes()
        over_budget = max_bytes > budget

        # Hybrid trigger: a table that has actually OOM'd repeatedly is repartitioned even when its
        # largest partition looks within budget — the compressed at-rest size under-counts the merge's
        # real working set (e.g. wide nested-JSON columns that decompress far more than typical data).
        # Only query the OOM log when the size check didn't already trip: an over-budget table
        # repartitions regardless, so the count would only feed observability props there — skip the
        # per-sync indexed COUNT for it and report 0.
        if over_budget:
            oom_count = 0
            oom_triggered = False
        else:
            oom_count = await asyncio.to_thread(
                ExternalDataSchemaOOMEvent.recent_count, schema, days=repartition_oom_window_days()
            )
            oom_triggered = oom_count >= repartition_oom_threshold()

        # A table with this shape is one that the coarsening path evaluates on each run, and its
        # gates open with time (layout age, days without an OOM). Such a table is never healthy, so
        # the next run measures it again.
        coarsen_candidate = (
            len(partition_bytes) >= COARSEN_MIN_PARTITIONS and max_bytes * COARSEN_TRIGGER_DIVISOR <= budget
        )
        await asyncio.to_thread(
            schema.record_partition_measurement,
            max_bytes,
            {
                "job_id": str(job.id),
                "phase": phase,
                "budget": budget,
                "healthy": not over_budget and not oom_triggered and not coarsen_candidate,
            },
        )

        if not over_budget and not oom_triggered:
            await logger.adebug(
                f"repartition: not needed, within budget and no repeated OOMs schema_id={schema.id} "
                f"max_partition_bytes={max_bytes} budget_bytes={budget} recent_oom_count={oom_count} "
                f"partition_count={len(partition_bytes)}",
                schema_id=str(schema.id),
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                recent_oom_count=oom_count,
                partition_count=len(partition_bytes),
            )
            await maybe_flag_for_coarsening(
                schema, source, job, partition_bytes, oom_count, logger, budget=budget, max_bytes=max_bytes
            )
            return

        # An OOM-triggered split targets roughly half the current largest partition (see `split_budget`
        # below). Refuse when that result would fall under the floor: partition size cannot be what is
        # killing a table whose partitions are already that small, and without this guard oom_history
        # drives the scheme finer tier by tier until it bottoms out (e.g. datetime at hour) and then
        # re-measures and re-emits the skip on every cooldown expiry forever.
        split_budget = budget if over_budget else max(1, max_bytes // 2)
        floor = min_splittable_partition_bytes()
        if not over_budget and split_budget < floor:
            await logger.adebug(
                f"repartition: OOM history present but a split would produce partitions under the floor, "
                f"so partitioning is not the cause, leaving layout alone schema_id={schema.id} "
                f"max_partition_bytes={max_bytes} split_budget_bytes={split_budget} floor_bytes={floor} "
                f"budget_bytes={budget} recent_oom_count={oom_count}",
                schema_id=str(schema.id),
                max_partition_bytes=max_bytes,
                split_budget_bytes=split_budget,
                floor_bytes=floor,
                budget_bytes=budget,
                recent_oom_count=oom_count,
            )
            # A table blocked here has OOM history *and* partitions too small to split, which is the
            # exact state the over-split backlog is in. Evaluate coarsening rather than returning: the
            # automatic path still refuses it on the same OOM history, but an operator nomination gets
            # its chance, and this is the only route by which a nominated table reaches coarsening at
            # all once its OOM count crosses the split threshold.
            await maybe_flag_for_coarsening(
                schema, source, job, partition_bytes, oom_count, logger, budget=budget, max_bytes=max_bytes
            )
            return

        trigger_reason = "proactive_threshold" if over_budget else "oom_history"

        if schema.coarsen_requested is not None:
            # The table needs the opposite direction, so the nomination is moot — and left set it would
            # force a Delta-log measurement on every sync forever, since nothing else consumes it here.
            await asyncio.to_thread(schema.clear_coarsen_requested)
            await logger.ainfo(
                f"repartition: coarsening nomination cleared, table needs a finer layout instead "
                f"schema_id={schema.id} trigger_reason={trigger_reason} max_partition_bytes={max_bytes}",
                schema_id=str(schema.id),
                trigger_reason=trigger_reason,
                max_partition_bytes=max_bytes,
            )

        if schema.repartition_pending is not None:
            await logger.adebug(
                f"repartition: needs repartition (trigger_reason={trigger_reason}) but already queued for the next "
                f"run schema_id={schema.id} max_partition_bytes={max_bytes} budget_bytes={budget} "
                f"repartition_pending={schema.repartition_pending}",
                schema_id=str(schema.id),
                trigger_reason=trigger_reason,
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                repartition_pending=schema.repartition_pending,
            )
            return

        cooldown_remaining = _cooldown_seconds_remaining(schema)
        if cooldown_remaining > 0:
            await logger.adebug(
                f"repartition: needs repartition (trigger_reason={trigger_reason}) but skipped, in post-repartition "
                f"cooldown schema_id={schema.id} max_partition_bytes={max_bytes} budget_bytes={budget} "
                f"last_repartition_at={schema.last_repartition_at} cooldown_seconds_remaining={int(cooldown_remaining)}",
                schema_id=str(schema.id),
                trigger_reason=trigger_reason,
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                last_repartition_at=schema.last_repartition_at,
                cooldown_seconds_remaining=int(cooldown_remaining),
            )
            return

        # `split_budget` was computed with the floor check above: an over-budget table targets the
        # budget, while an OOM-triggered one targets roughly half its current largest partition to force
        # a meaningfully finer scheme (md5 grows buckets, numerical halves the row-size, datetime steps
        # one tier finer).
        target, reason = select_repartition_target(schema, partition_bytes, split_budget)
        if target is None:
            # Needs repartition but nothing finer to do (datetime at hour, numerical can't shrink, unpartitionable).
            # `reason` is reported on the metric + event so a skipped table is diagnosable.
            DELTA_REPARTITION_SKIP_TOTAL.labels(reason=reason).inc()
            props = base_event_props(schema, source, str(job.id))
            props.update(
                {
                    "max_partition_bytes_before": max_bytes,
                    "reason": reason,
                    "trigger_reason": trigger_reason,
                    "recent_oom_count": oom_count,
                }
            )
            await asyncio.to_thread(capture_repartition_event, "warehouse_repartition_skipped", props)
            await logger.adebug(
                f"repartition: needs repartition but skipped, no finer partitioning target available "
                f"schema_id={schema.id} reason={reason} max_partition_bytes={max_bytes} budget_bytes={budget} "
                f"partition_mode={schema.partition_mode} partition_format={schema.partition_format} "
                f"partition_count={len(partition_bytes)}",
                schema_id=str(schema.id),
                reason=reason,
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                partition_mode=schema.partition_mode,
                partition_format=schema.partition_format,
                partition_count=len(partition_bytes),
            )
            if reason not in EXPECTED_SKIP_REASONS:
                capture_exception(Exception(f"Repartition needed but skipped for schema {schema.id}: {reason}"))
            # Engage the cooldown even though no rewrite happened: the trigger (over budget or repeated
            # OOMs) is still true next sync and the table's scheme can't go finer, so without this we
            # re-measure and re-emit the skip event on every 5-minute sync forever. The
            # cooldown re-evaluates at most daily; a real change to the table clears it via a later
            # successful repartition.
            await asyncio.to_thread(schema.stamp_last_repartition_at)
            return

        pending = {**target.to_dict(), "trigger_reason": trigger_reason, "attempts": 0}
        await asyncio.to_thread(schema.set_repartition_pending, pending)

        props = base_event_props(schema, source, str(job.id))
        props.update(
            {
                "max_partition_bytes_before": max_bytes,
                "trigger_reason": trigger_reason,
                "recent_oom_count": oom_count,
                # An unpartitioned table's target has mode None ("enable partitioning, auto-detect
                # the scheme on the first rewrite batch"). Emit an explicit "auto" so dashboards can
                # render the target scheme instead of a null — half of all flagged events are this
                # case, and a null here NULL-poisons any string built from the scheme properties.
                "partition_mode_after": target.partition_mode or "auto",
                "partition_format_after": target.partition_format,
                "partition_count_after": target.partition_count,
                "partition_size_after": target.partition_size,
            }
        )
        await asyncio.to_thread(capture_repartition_event, "warehouse_repartition_flagged", props)
        await logger.adebug(
            f"repartition: flagged for next run schema_id={schema.id} max_partition_bytes={max_bytes} "
            f"budget_bytes={budget} target_mode={target.partition_mode} target_format={target.partition_format} "
            f"target_count={target.partition_count} target_size={target.partition_size}",
            schema_id=str(schema.id),
            max_partition_bytes=max_bytes,
            budget_bytes=budget,
            target_mode=target.partition_mode,
            target_format=target.partition_format,
            target_count=target.partition_count,
            target_size=target.partition_size,
        )
    except Exception as e:
        # Detection is best-effort; never fail post-load over it. `record_partition_measurement` and
        # the other DB writes above can hit a transient app-DB blip (pgbouncer pooler drop, or its
        # server_login_retry cooldown outliving retry_on_db_connection_drop's single retry) — the
        # same class of noise `_maybe_flag_pre_extraction` (repartition_table.py) already filters
        # out with this same classifier, so this best-effort detection function should too.
        if is_transient_maintenance_error(e):
            await logger.awarning(
                f"repartition: detection failed with a transient infra error schema_id={schema.id}",
                schema_id=str(schema.id),
            )
            return
        await logger.aexception(f"repartition: detection failed schema_id={schema.id}", schema_id=str(schema.id))
        capture_exception(e)
