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
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition import (
    measure_partition_bytes,
    select_repartition_target,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_REPARTITION_SKIP_TOTAL,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

WAREHOUSE_AUTO_REPARTITION_FLAG = "data-warehouse-auto-repartition"

# Don't repartition the same table more than once a day — the budget has headroom, so a table that
# trips repeatedly should converge over a few daily cycles, not thrash every sync.
REPARTITION_COOLDOWN_SECONDS = 24 * 60 * 60

# Give up (and alert) after this many consecutive failed attempts so a permanently-failing table
# doesn't re-attempt the rewrite on every sync forever.
MAX_REPARTITION_ATTEMPTS = 3


def target_partition_bytes() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_TARGET_PARTITION_BYTES", 500_000_000))


def repartition_oom_threshold() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD", 3))


def repartition_oom_window_days() -> int:
    return int(getattr(settings, "DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS", 7))


def is_auto_repartition_enabled(schema: ExternalDataSchema) -> bool:
    """Evaluate the rollout flag for this schema.

    `schema_id`, `team_id`, and `source_type` are passed as person properties so the flag can be
    released to a single table — set a release condition `schema_id = <id>` to dogfood the controller
    on one schema before rolling out by team/org/project.
    """
    from posthog.models import Team

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=schema.team_id)
    except Team.DoesNotExist:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_AUTO_REPARTITION_FLAG,
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
            return

        trigger_reason = "proactive_threshold" if over_budget else "oom_history"

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
                f"repartition: over budget but already queued for the next run schema_id={schema.id} "
                f"max_partition_bytes={max_bytes} budget_bytes={budget} repartition_pending={schema.repartition_pending}",
                schema_id=str(schema.id),
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                repartition_pending=schema.repartition_pending,
            )
            return

        cooldown_remaining = _cooldown_seconds_remaining(schema)
        if cooldown_remaining > 0:
            await logger.adebug(
                f"repartition: over budget but skipped, in post-repartition cooldown schema_id={schema.id} "
                f"max_partition_bytes={max_bytes} budget_bytes={budget} last_repartition_at={schema.last_repartition_at} "
                f"cooldown_seconds_remaining={int(cooldown_remaining)}",
                schema_id=str(schema.id),
                max_partition_bytes=max_bytes,
                budget_bytes=budget,
                last_repartition_at=schema.last_repartition_at,
                cooldown_seconds_remaining=int(cooldown_remaining),
            )
            return

        # OOM-triggered but within the size budget: the compressed size under-counted the working set,
        # so target roughly half the current largest partition to force a meaningfully finer scheme
        # (md5 grows buckets, numerical halves the row-size, datetime steps one tier finer).
        split_budget = budget if over_budget else max(1, max_bytes // 2)
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
                f"repartition: over budget but skipped, no finer partitioning target available "
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
            return

        pending = {**target.to_dict(), "trigger_reason": trigger_reason, "attempts": 0}
        await asyncio.to_thread(schema.set_repartition_pending, pending)

        props = base_event_props(schema, source, str(job.id))
        props.update(
            {
                "max_partition_bytes_before": max_bytes,
                "trigger_reason": trigger_reason,
                "recent_oom_count": oom_count,
                "partition_mode_after": target.partition_mode,
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
        # Detection is best-effort; never fail post-load over it.
        await logger.aexception(f"repartition: detection failed schema_id={schema.id}", schema_id=str(schema.id))
        capture_exception(e)
