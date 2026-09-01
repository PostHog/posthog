"""Detection + gating for the automated in-place repartition controller.

Measures per-partition size after a sync (cheap — read from the Delta log) and, when a table's
largest partition outgrows the memory-safe budget, records a `repartition_pending` target on the
schema. The next run's pre-extraction activity performs the rewrite (see `repartition.py` and
`workflow_activities/repartition_table.py`). Everything is observable via PostHog events.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import InterfaceError, OperationalError
from django.utils import timezone

import deltalake as deltalake
import posthoganalytics
from dateutil import parser
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.utils import retry_on_db_connection_drop
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

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

WAREHOUSE_AUTO_REPARTITION_FLAG = "data-warehouse-auto-repartition"
WAREHOUSE_AUTO_COARSEN_FLAG = "data-warehouse-auto-coarsen"
# Gates pausing a schema's imports while a multi-budget rewrite converges. Separate from the
# repartition flag, and off by default: repartitioning a table costs us worker time, pausing its
# imports costs the customer freshness, so the second is not a decision the first should make.
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

# Give up (and alert) after this many consecutive failed attempts so a permanently-failing table
# doesn't re-attempt the rewrite on every sync forever.
MAX_REPARTITION_ATTEMPTS = 3


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


def is_auto_repartition_enabled(schema: ExternalDataSchema) -> bool:
    return _is_flag_enabled(schema, WAREHOUSE_AUTO_REPARTITION_FLAG)


def is_auto_coarsen_enabled(schema: ExternalDataSchema) -> bool:
    return _is_flag_enabled(schema, WAREHOUSE_AUTO_COARSEN_FLAG)


def is_repartition_hold_enabled(schema: ExternalDataSchema) -> bool:
    return _is_flag_enabled(schema, WAREHOUSE_REPARTITION_HOLD_FLAG)


def _is_flag_enabled(schema: ExternalDataSchema, flag: str) -> bool:
    """Evaluate a rollout flag for this schema.

    `schema_id`, `team_id`, and `source_type` are passed as person properties so the flag can be
    released to a single table — set a release condition `schema_id = <id>` to dogfood the controller
    on one schema before rolling out by team/org/project.
    """
    from posthog.models import Team

    try:
        team = retry_on_db_connection_drop(lambda: Team.objects.only("uuid", "organization_id").get(id=schema.team_id))
    except Team.DoesNotExist:
        return False
    except (OperationalError, InterfaceError) as e:
        # retry_on_db_connection_drop already retried once; a second failure is a genuinely degraded
        # DB, not a bug here. Some callers (repartition_table.py) evaluate this flag with no enclosing
        # try/except, so this function's contract of "never raises, defaults to disabled" must hold on
        # its own.
        capture_exception(e)
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                person_properties={
                    "schema_id": str(schema.id),
                    "team_id": str(schema.team_id),
                    "source_type": schema.source.source_type,
                },
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


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

    Ordered cheapest first — in-memory shape gates, then the in-memory selector, then the database, and
    the feature flag (a Team fetch plus a PostHog API call) dead last. Post-load detection runs this
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

        if not await asyncio.to_thread(is_auto_coarsen_enabled, schema):
            await logger.adebug(
                f"repartition: table is over-fragmented but coarsening is disabled by feature flag "
                f"schema_id={schema.id} max_partition_bytes={max_bytes} partition_count={measured_partitions}",
                schema_id=str(schema.id),
                max_partition_bytes=max_bytes,
                partition_count=measured_partitions,
            )
            return _decline("flag_disabled")

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
    enabled: bool | None = None,
) -> None:
    """Measure partition sizes and, if over budget, record a `repartition_pending` target.

    Always records `max_partition_bytes` for observability (even when the controller is disabled or in
    cooldown). Setting the pending target is gated by the feature flag; the rewrite itself happens on
    the next run. Never raises — detection must not break post-load.

    Pass `enabled` when the caller has already evaluated the rollout flag for this schema (each
    evaluation is a `Team.objects.get()` plus a PostHog API call) to avoid re-evaluating it here; when
    omitted it is evaluated lazily, only once the table is confirmed over budget.
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
        await asyncio.to_thread(schema.record_partition_measurement, max_bytes)

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
        # emits a skipped event plus an exception on every cooldown expiry forever.
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

        if enabled is None:
            enabled = await asyncio.to_thread(is_auto_repartition_enabled, schema)
        if not enabled:
            await logger.adebug(
                f"repartition: needs repartition but skipped, controller disabled by feature flag "
                f"schema_id={schema.id} trigger_reason={trigger_reason} max_partition_bytes={max_bytes} "
                f"budget_bytes={budget} recent_oom_count={oom_count}",
                schema_id=str(schema.id),
                trigger_reason=trigger_reason,
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                recent_oom_count=oom_count,
            )
            return

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
            DELTA_REPARTITION_SKIP_TOTAL.labels(team_id=str(schema.team_id), reason=reason).inc()
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
            capture_exception(Exception(f"Repartition needed but skipped for schema {schema.id}: {reason}"))
            # Engage the cooldown even though no rewrite happened: the trigger (over budget or repeated
            # OOMs) is still true next sync and the table's scheme can't go finer, so without this we
            # re-measure, re-emit the skip event, and re-alert on every 5-minute sync forever. The
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
