"""Partitioning of one warehouse table: staging a repartition, and reading its history.

Staff in PostHog Admin and customers through the API stage a repartition through `stage_repartition`,
so both paths validate the scheme and check the partition budget the same way.
"""

import math
import time
import statistics
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, assert_never, cast, get_args

from django.db.models import Q

import deltalake

from posthog.dataclasses import frozen
from posthog.temporal.common.client import sync_connect
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.facade.api import pause_external_data_schedule, unpause_external_data_schedule
from products.warehouse_sources.backend.ad_hoc_sync import is_schedule_paused, start_external_data_workflow
from products.warehouse_sources.backend.facade.contracts import RepartitionRequest
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    PartitionPolicy,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.repartition_history import (
    ExternalDataSchemaRepartition,
    RepartitionStatus,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    build_delta_table_uri,
    delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    DATETIME_FORMAT_TIERS,
    measure_partition_bytes,
    simulate_datetime_coarsening,
    simulate_modulo_coarsening,
    simulate_numerical_coarsening,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    WAREHOUSE_PARTITIONING_CONTROLS_FLAG,
    base_event_props,
    capture_repartition_event,
    cooldown_seconds_remaining,
    split_budget_bytes,
)
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_loaded_team_flag_enabled
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)

if TYPE_CHECKING:
    from posthog.models import Team

# Source of truth lives in pipeline.typings. Re-deriving here keeps the choices in sync if a new format or mode is
# ever added.
PARTITION_FORMAT_CHOICES: tuple[str, ...] = get_args(PartitionFormat)
PARTITION_MODE_CHOICES: tuple[str, ...] = get_args(PartitionMode)

RepartitionTrigger = Literal["admin", "user"]

# The history the API returns, newest first. Older rows stay in the table.
HISTORY_LIMIT = 50
# The jobs the sync stats read, newest first, so one busy table cannot make the request slow.
SYNC_STATS_JOB_LIMIT = 2000


def partitioning_controls_enabled_for_team(team: "Team") -> bool:
    """Whether the team can choose partitioning policies and repartition tables. Reads no row."""
    return is_loaded_team_flag_enabled(team, WAREHOUSE_PARTITIONING_CONTROLS_FLAG)


class RepartitionRefusal(StrEnum):
    INVALID_SCHEME = "invalid_scheme"
    OVER_BUDGET = "over_budget"
    UNKNOWN_SIZE = "unknown_size"
    READ_FAILED = "read_failed"
    UNSUPPORTED = "unsupported"
    BUSY = "busy"
    COOLDOWN = "cooldown"
    PAUSE_FAILED = "pause_failed"


@frozen
class StagedRepartition:
    label: str
    target: dict[str, Any]


@frozen
class RepartitionOutcome:
    """What `stage_repartition` did. `refusal` is None when the target was staged."""

    message: str
    refusal: RepartitionRefusal | None = None
    workflow_id: str | None = None
    run_started: bool = False

    @property
    def ok(self) -> bool:
        return self.refusal is None


class _Busy(Exception):
    pass


def build_repartition_target(
    schema: ExternalDataSchema, request: RepartitionRequest, *, trigger_reason: RepartitionTrigger
) -> StagedRepartition | str:
    """The `repartition_pending` target for the request, or why the request cannot be used."""
    # Mode falls back to the schema's current mode for a pure in-place repartition, and must resolve to a known
    # mode: the pipeline picks one on the first sync, so before that the caller chooses.
    new_mode = request.partition_mode or schema.partition_mode
    if new_mode not in PARTITION_MODE_CHOICES:
        return (
            f"Invalid partition_mode: {new_mode!r}. Choose one of {', '.join(PARTITION_MODE_CHOICES)} "
            "(or run a sync first so the pipeline picks one)."
        )
    new_mode = cast(PartitionMode, new_mode)
    mode_changed = new_mode != schema.partition_mode

    # `staged` is only a validated carrier of the chosen knobs for the pending target below.
    staged: dict[str, Any] = {"partition_mode_override": new_mode}
    label_bits: list[str] = []
    if mode_changed:
        label_bits.append(f"partition_mode: {schema.partition_mode!r} → {new_mode!r}")

    # Keys are optional: omitting them keeps the existing keys (in-place repartition). When switching INTO
    # datetime or numerical they are required, because the existing composite PK is usually unsuitable for
    # single-column bucketing.
    keys = list(request.partitioning_keys)

    if new_mode == "datetime":
        if keys:
            if len(keys) != 1:
                return (
                    "datetime mode needs exactly one partitioning key — the date/timestamp "
                    "column to bucket on (e.g. action_date)."
                )
            staged["partitioning_keys_override"] = keys
            label_bits.append(f"keys={keys}")
        elif mode_changed:
            return (
                "Switching to datetime needs exactly one partitioning key — the date/timestamp "
                "column to bucket on (e.g. action_date)."
            )
        if request.partition_format not in PARTITION_FORMAT_CHOICES:
            return f"Invalid partition_format: {request.partition_format!r}."
        # partition_format already survives the reset and is read directly by the pipeline.
        staged["partition_format"] = request.partition_format
        label_bits.append(f"format={request.partition_format!r}")
    elif new_mode == "numerical":
        if keys:
            if len(keys) != 1:
                return "numerical mode needs exactly one integer partitioning key."
            staged["partitioning_keys_override"] = keys
            label_bits.append(f"keys={keys}")
        elif mode_changed:
            return "Switching to numerical needs exactly one integer partitioning key."
        if request.partition_size is None:
            return "partition_size is required."
        if request.partition_size < 1:
            return "partition_size must be at least 1."
        staged["partition_size_override"] = request.partition_size
        label_bits.append(f"partition_size={request.partition_size}")
    elif new_mode == "md5":
        if request.partition_count is None:
            return "partition_count is required."
        if request.partition_count < 1:
            return "partition_count must be at least 1."
        if keys:
            staged["partitioning_keys_override"] = keys
            label_bits.append(f"keys={keys}")
        elif mode_changed:
            # Switching INTO md5: clear any stale keys override so md5 falls back to the table's primary keys
            # instead of a date column pinned by an earlier datetime attempt.
            staged["partitioning_keys_override"] = None
        staged["partition_count_override"] = request.partition_count
        label_bits.append(f"partition_count={request.partition_count}")
    else:
        # Exhaustive over PartitionMode, so mypy asks for an update here if a new mode is ever added.
        assert_never(new_mode)

    return StagedRepartition(
        label=", ".join(label_bits) if label_bits else "repartition",
        # The next run's pre-extraction activity rewrites the existing S3 data into this scheme in place: no
        # source re-pull, no reset.
        target={
            "partition_mode": new_mode,
            "partition_format": staged.get("partition_format"),
            "partition_count": staged.get("partition_count_override"),
            "partition_size": staged.get("partition_size_override"),
            "partition_keys": (
                staged.get("partitioning_keys_override") or schema.partitioning_keys or schema.primary_key_columns or []
            ),
            "trigger_reason": trigger_reason,
            "attempts": 0,
        },
    )


def measure_live_partition_bytes(schema: ExternalDataSchema) -> dict[str | None, int] | None:
    """Bytes per partition of the table on disk, from the Delta log. None when there is no table yet."""
    uri = build_delta_table_uri(schema.folder_path(), schema.resolved_s3_folder_name or schema.name)
    storage_options = delta_storage_options()
    if not deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
        return None
    return measure_partition_bytes(deltalake.DeltaTable(uri, storage_options=storage_options))


def estimate_largest_partition_bytes(
    schema: ExternalDataSchema, partition_bytes: dict[str | None, int], target: dict[str, Any]
) -> int | None:
    """An upper estimate of the largest partition after rewriting into `target`, or None when unknown.

    Exact where the new partitions are unions of the old ones (a coarser datetime tier, an md5 count that
    divides the current one, a numerical size that is a multiple of the current one). A finer layout of the
    same scheme cannot grow a partition. An md5 layout over the primary key spreads rows evenly. Any other
    change depends on values the Delta log does not record.
    """
    if not partition_bytes:
        return 0
    total = sum(partition_bytes.values())
    current_max = max(partition_bytes.values())
    mode = target["partition_mode"]
    keys = list(target.get("partition_keys") or [])
    same_keys = keys == list(schema.partitioning_keys or schema.primary_key_columns or [])

    if mode == "md5" and keys and keys == list(schema.primary_key_columns or []):
        if (
            schema.partition_mode == "md5"
            and schema.partition_count
            and schema.partition_count % target["partition_count"] == 0
        ):
            simulated = simulate_modulo_coarsening(partition_bytes, target["partition_count"])
            if simulated:
                return max(simulated.values())
        return math.ceil(total / target["partition_count"])

    if mode != schema.partition_mode or not same_keys:
        return None

    if mode == "datetime":
        current_format: PartitionFormat = schema.partition_format or "month"
        new_format: PartitionFormat = target["partition_format"]
        if DATETIME_FORMAT_TIERS.index(new_format) >= DATETIME_FORMAT_TIERS.index(current_format):
            return current_max
        simulated = simulate_datetime_coarsening(partition_bytes, current_format, new_format)
        return max(simulated.values()) if simulated else None

    if mode == "md5":
        current_count = schema.partition_count
        new_count = target["partition_count"]
        if not current_count:
            return None
        if current_count % new_count == 0:
            simulated = simulate_modulo_coarsening(partition_bytes, new_count)
            return max(simulated.values()) if simulated else None
        # Rows move between buckets, but the hash keeps the current skew between buckets.
        return math.ceil(current_max * current_count / new_count)

    if mode == "numerical":
        current_size = schema.partition_size
        new_size = target["partition_size"]
        if not current_size:
            return None
        if new_size <= current_size and current_size % new_size == 0:
            return current_max
        if new_size < current_size:
            # A new bucket can straddle two old ones.
            return 2 * current_max
        if new_size % current_size == 0:
            simulated = simulate_numerical_coarsening(partition_bytes, new_size // current_size)
            return max(simulated.values()) if simulated else None
        return None

    return None


def _budget_refusal(
    schema: ExternalDataSchema, target: dict[str, Any], *, refuse_unknown: bool
) -> tuple[RepartitionRefusal, str] | None:
    """Why the target must not be staged because of its partition sizes, or None when it fits.

    The rewrite has no size check of its own for a chosen target, and a partition over the budget is what
    makes a merge run out of memory.
    """
    try:
        partition_bytes = measure_live_partition_bytes(schema)
    except Exception as e:
        return RepartitionRefusal.READ_FAILED, f"Could not read the table's current partitions: {type(e).__name__}."
    if not partition_bytes:
        # Nothing on disk yet, so the first sync writes the new layout and nothing is rewritten.
        return None
    budget = split_budget_bytes(schema)
    if sum(partition_bytes.values()) <= budget:
        return None
    estimate = estimate_largest_partition_bytes(schema, partition_bytes, target)
    if estimate is None:
        if refuse_unknown:
            return (
                RepartitionRefusal.UNKNOWN_SIZE,
                "PostHog can't predict partition sizes for this change. Keep the current mode and keys, "
                "or choose a scheme whose partitions are unions of the current ones.",
            )
        return None
    if estimate > budget:
        return (
            RepartitionRefusal.OVER_BUDGET,
            f"The largest partition would hold about {estimate:,} bytes, over the {budget:,} byte limit. "
            "Choose a finer scheme.",
        )
    return None


def _limits_refusal(schema: ExternalDataSchema) -> tuple[RepartitionRefusal, str] | None:
    if schema.is_cdc:
        return RepartitionRefusal.UNSUPPORTED, "Tables synced with change data capture can't be repartitioned."
    if not schema.should_sync:
        return RepartitionRefusal.UNSUPPORTED, "Turn on syncing for this table first."
    if _is_busy(schema.sync_type_config or {}):
        return RepartitionRefusal.BUSY, "A repartition is already queued or running for this table."
    remaining = cooldown_seconds_remaining(schema)
    if remaining > 0:
        hours = math.ceil(remaining / 3600)
        return (
            RepartitionRefusal.COOLDOWN,
            f"This table was repartitioned recently. Try again in about {hours} hour{'s' if hours != 1 else ''}.",
        )
    return None


def _is_busy(config: dict[str, Any]) -> bool:
    return any(
        config.get(key) is not None for key in ("repartition_pending", "repartition_swap", "delta_revive_required")
    )


def stage_repartition(
    schema: ExternalDataSchema,
    request: RepartitionRequest,
    *,
    trigger_reason: RepartitionTrigger,
    requested_by_id: int | None = None,
) -> RepartitionOutcome:
    """Validate a chosen scheme, stage it as `repartition_pending`, and start one run that rewrites the table.

    Both callers get the scheme validation and the budget check. A customer (`user`) also gets the limits: one
    repartition at a time, the cooldown after the last one, and no scheme whose size can't be predicted. A
    customer's table then moves to the `manual` policy, so the controller does not undo the chosen layout.
    """
    is_user = trigger_reason == "user"
    if is_user:
        limits = _limits_refusal(schema)
        if limits is not None:
            return RepartitionOutcome(refusal=limits[0], message=limits[1])

    staged = build_repartition_target(schema, request, trigger_reason=trigger_reason)
    if isinstance(staged, str):
        return RepartitionOutcome(refusal=RepartitionRefusal.INVALID_SCHEME, message=staged)

    budget = _budget_refusal(schema, staged.target, refuse_unknown=is_user)
    if budget is not None:
        return RepartitionOutcome(refusal=budget[0], message=budget[1])

    outcome = _pause_save_and_resync(schema, staged, refuse_if_busy=is_user)
    if not outcome.ok:
        return outcome

    props = base_event_props(schema, schema.source, None)
    props.update(
        {
            "trigger_reason": trigger_reason,
            "partition_mode_after": staged.target["partition_mode"],
            "partition_format_after": staged.target["partition_format"],
            "partition_count_after": staged.target["partition_count"],
            "partition_size_after": staged.target["partition_size"],
            "partition_keys_after": staged.target["partition_keys"],
            "max_partition_bytes_before": schema.max_partition_bytes,
        }
    )
    capture_repartition_event("warehouse_repartition_flagged", props, requested_by_id=requested_by_id)

    if is_user and schema.partition_policy != PartitionPolicy.MANUAL:
        schema.partition_policy = PartitionPolicy.MANUAL
        schema.save(update_fields=["partition_policy", "updated_at"])
    return outcome


def _pause_save_and_resync(
    schema: ExternalDataSchema, staged: StagedRepartition, *, refuse_if_busy: bool
) -> RepartitionOutcome:
    # Pause the schedule, stage the target, and trigger a single non-billable run whose pre-extraction activity
    # repartitions in place from S3 (no source pull) before syncing.
    #
    # Pause first so the scheduled workflow doesn't race with this one (Temporal's "OnlyOne" overlap policy is
    # per-schedule, not across schedule + ad-hoc workflow). If the schedule was already paused by hand, skip
    # auto-unpause so this does not undo that.
    try:
        client = sync_connect()
    except Exception as e:
        return RepartitionOutcome(
            refusal=RepartitionRefusal.PAUSE_FAILED, message=f"Failed to connect to Temporal: {e}."
        )

    was_paused = is_schedule_paused(client, str(schema.id))
    paused_now = False
    if not was_paused:
        try:
            pause_external_data_schedule(str(schema.id))
            paused_now = True
        except Exception as e:
            return RepartitionOutcome(
                refusal=RepartitionRefusal.PAUSE_FAILED, message=f"Failed to pause schedule before resync: {e}."
            )

    workflow_id = f"{schema.id}-admin-repartition-{int(time.time())}"
    previous_marker = (schema.sync_type_config or {}).get("admin_unpause_schedule_after_run")

    def stage(config: dict[str, Any]) -> None:
        # Under the row lock, so two requests cannot both stage a target.
        if refuse_if_busy and _is_busy(config):
            raise _Busy
        config["repartition_pending"] = staged.target
        # Read by `resume_schedule_after_ad_hoc_run` when the run completes.
        if paused_now or previous_marker:
            config["admin_unpause_schedule_after_run"] = workflow_id

    try:
        schema.sync_type_config = update_sync_type_config_keys(schema.id, schema.team_id, mutate=stage)
    except _Busy:
        if paused_now:
            _unpause_quietly(schema)
        return RepartitionOutcome(
            refusal=RepartitionRefusal.BUSY, message="A repartition is already queued or running for this table."
        )

    inputs = ExternalDataWorkflowInputs(
        team_id=schema.team_id,
        external_data_source_id=schema.source.id,
        external_data_schema_id=schema.id,
        billable=False,
        reset_pipeline=None,
    )
    try:
        start_external_data_workflow(client, workflow_id, inputs)
    except Exception as e:
        # Best-effort rollback of the pause taken above. Without this, a failed workflow start leaves the schedule
        # paused forever (the marker is read by the workflow at completion, and there's no workflow if start
        # failed) and the marker orphaned in sync_type_config. The target stays staged for the next sync.
        if paused_now:
            _unpause_quietly(schema)
            _restore_marker(schema, None)
        elif previous_marker:
            _restore_marker(schema, previous_marker)
        return RepartitionOutcome(
            message=f"Saved {staged.label}, but failed to trigger run: {e}. The next sync runs the repartition."
        )

    pause_note = (
        " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
        if paused_now
        else " Schedule was already paused; leaving it paused."
    )
    return RepartitionOutcome(
        message=f"{staged.label}. Triggered non-billable in-place repartition (no source pull) "
        f"(workflow_id={workflow_id}).{pause_note}",
        workflow_id=workflow_id,
        run_started=True,
    )


def _unpause_quietly(schema: ExternalDataSchema) -> None:
    try:
        unpause_external_data_schedule(str(schema.id))
    except Exception:
        pass


def _restore_marker(schema: ExternalDataSchema, marker: str | None) -> None:
    try:
        if marker is None:
            schema.sync_type_config = update_sync_type_config_keys(
                schema.id, schema.team_id, removes=["admin_unpause_schedule_after_run"]
            )
        else:
            schema.sync_type_config = update_sync_type_config_keys(
                schema.id, schema.team_id, updates={"admin_unpause_schedule_after_run": marker}
            )
    except Exception:
        pass


# Reading the history.


@frozen
class PartitioningSummary:
    policy: str
    partition_mode: str | None
    partition_format: str | None
    partition_count: int | None
    partition_size: int | None
    partitioning_keys: tuple[str, ...] | None
    max_partition_bytes: int | None
    healthy: bool | None
    last_repartition_at: str | None
    repartition_pending: bool


def partitioning_summary(schema: ExternalDataSchema) -> PartitioningSummary:
    measurement = schema.partition_measurement or {}
    healthy = measurement.get("healthy")
    keys = schema.partitioning_keys
    return PartitioningSummary(
        policy=schema.partition_policy,
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_count=schema.partition_count,
        partition_size=schema.partition_size,
        partitioning_keys=tuple(keys) if keys is not None else None,
        max_partition_bytes=schema.max_partition_bytes,
        healthy=healthy if isinstance(healthy, bool) else None,
        last_repartition_at=schema.last_repartition_at,
        repartition_pending=schema.repartition_pending is not None or schema.repartition_swap is not None,
    )


@frozen
class SyncJobTiming:
    job_id: str
    created_at: datetime
    duration_seconds: float
    rows_synced: int | None


@frozen
class SyncStatsWindow:
    """Sync stats for the jobs between two completed repartitions. `start` is None before the first one."""

    start: datetime | None
    end: datetime | None
    repartition_id: str | None
    job_count: int
    median_duration_seconds: float | None
    p90_duration_seconds: float | None
    median_rows_per_second: float | None


def _percentile(sorted_values: Sequence[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    # Nearest rank, so the result is always a duration a job really took.
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _window_stats(
    jobs: Sequence[SyncJobTiming], start: datetime | None, end: datetime | None, repartition_id: str | None
) -> SyncStatsWindow:
    in_window = [
        job for job in jobs if (start is None or job.created_at >= start) and (end is None or job.created_at < end)
    ]
    durations = sorted(job.duration_seconds for job in in_window)
    rates = [
        job.rows_synced / job.duration_seconds for job in in_window if job.rows_synced and job.duration_seconds > 0
    ]
    return SyncStatsWindow(
        start=start,
        end=end,
        repartition_id=repartition_id,
        job_count=len(in_window),
        median_duration_seconds=statistics.median(durations) if durations else None,
        p90_duration_seconds=_percentile(durations, 0.9),
        median_rows_per_second=statistics.median(rates) if rates else None,
    )


def sync_stats_windows(
    repartitions: Sequence[ExternalDataSchemaRepartition], jobs: Sequence[SyncJobTiming]
) -> list[SyncStatsWindow]:
    """Sync stats for each stretch of time between completed repartitions, oldest first.

    `jobs` must already leave out the jobs that ran a rewrite, because their duration includes it.
    """
    boundaries = sorted(
        (row for row in repartitions if row.status == RepartitionStatus.COMPLETED and row.finished_at is not None),
        key=lambda row: cast(datetime, row.finished_at),
    )
    windows: list[SyncStatsWindow] = []
    start: datetime | None = None
    opened_by: str | None = None
    for row in boundaries:
        windows.append(_window_stats(jobs, start, row.finished_at, opened_by))
        start = row.finished_at
        opened_by = str(row.id)
    windows.append(_window_stats(jobs, start, None, opened_by))
    return windows


def _rewrite_job_ids(schema: ExternalDataSchema) -> set[str]:
    # A row that reached `running`, or that a rewrite run reported (it carries the run's trigger), belongs to a
    # job whose duration includes the rewrite. The `manual` over-budget note has no trigger and ran no rewrite.
    return {
        job_id
        for job_id in ExternalDataSchemaRepartition.objects.for_team(schema.team_id)
        .filter(schema_id=schema.id, job_id__isnull=False)
        .filter(
            Q(status__in=[RepartitionStatus.RUNNING, RepartitionStatus.COMPLETED, RepartitionStatus.FAILED])
            | Q(status=RepartitionStatus.SKIPPED, trigger_reason__isnull=False)
        )
        .values_list("job_id", flat=True)
        if job_id
    }


def sync_job_timings(schema: ExternalDataSchema) -> list[SyncJobTiming]:
    excluded = _rewrite_job_ids(schema)
    rows = (
        ExternalDataJob.objects.filter(
            team_id=schema.team_id,
            schema_id=schema.id,
            status=ExternalDataJob.Status.COMPLETED,
            finished_at__isnull=False,
        )
        .order_by("-created_at")
        .values_list("id", "created_at", "finished_at", "rows_synced")[:SYNC_STATS_JOB_LIMIT]
    )
    return [
        SyncJobTiming(
            job_id=str(job_id),
            created_at=created_at,
            duration_seconds=max(0.0, (finished_at - created_at).total_seconds()),
            rows_synced=rows_synced,
        )
        for job_id, created_at, finished_at, rows_synced in rows
        if str(job_id) not in excluded
    ]


@frozen
class PartitioningHistory:
    summary: PartitioningSummary
    repartitions: list[ExternalDataSchemaRepartition]
    sync_windows: list[SyncStatsWindow]


def partitioning_history(schema: ExternalDataSchema) -> PartitioningHistory:
    repartitions = list(
        ExternalDataSchemaRepartition.objects.for_team(schema.team_id)
        .filter(schema_id=schema.id)
        .select_related("requested_by")
        .order_by("-created_at")[:HISTORY_LIMIT]
    )
    return PartitioningHistory(
        summary=partitioning_summary(schema),
        repartitions=repartitions,
        sync_windows=sync_stats_windows(repartitions, sync_job_timings(schema)),
    )
