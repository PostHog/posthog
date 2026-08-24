"""Syncs per-scanner schedules with the ReplayScanner table on every tick, and reaps orphaned observations."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import (
    MAX_ERROR_MESSAGE_CHARS,
    resolve_failure_type,
    truncate_for_temporal_payload,
    unwrap_temporal_cause,
)

from products.replay_vision.backend.temporal.constants import (
    INLINE_SCANNER_REAP_TIMEOUT,
    LIST_ENABLED_SCANNERS_TIMEOUT,
    LIST_SCANNER_SCHEDULES_TIMEOUT,
    REAP_BACKFILL_SCHEDULES_TIMEOUT,
    REAP_ORPHANED_OBSERVATIONS_HEARTBEAT_TIMEOUT,
    REAP_ORPHANED_OBSERVATIONS_TIMEOUT,
    REAP_STUCK_VISION_ACTION_RUNS_TIMEOUT,
    RECONCILE_SCHEDULE_OP_TIMEOUT,
    RECONCILER_EXECUTION_TIMEOUT,
    RECONCILER_INTERVAL,
    RECONCILER_SCHEDULE_ID,
    RECONCILER_SYSTEMIC_FAILURE_MIN_OPS,
    RECONCILER_WORKFLOW_ID,
    RECONCILER_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.reconciler_types import (
    DeleteScannerScheduleActivityInputs,
    ReconcileScannerSchedulesInputs,
    ReconcileScannerSchedulesResult,
    UpsertScannerScheduleActivityInputs,
)

if TYPE_CHECKING:
    from temporalio.client import Client


def _describe_failure(scanner_id: UUID, err: BaseException) -> str:
    # Unwrap Temporal's ActivityError wrapper to the underlying cause; the wrapper repr is a constant
    # "Activity task failed" that names no scanner and no cause. Bound the message so a big remote body
    # can't blow the Temporal payload limit.
    cause = unwrap_temporal_cause(err) or err
    message = truncate_for_temporal_payload(str(cause), MAX_ERROR_MESSAGE_CHARS)
    return f"{scanner_id}: {resolve_failure_type(cause)}: {message}"


# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities import (
        delete_scanner_schedule_activity,
        list_enabled_scanners_activity,
        list_scanner_schedules_activity,
        reap_backfill_schedules_activity,
        reap_childless_inline_scanners_activity,
        reap_orphaned_observations_activity,
        reap_stuck_vision_action_runs_activity,
        upsert_scanner_schedule_activity,
    )


@workflow.defn(name=RECONCILER_WORKFLOW_NAME)
class ReconcileScannerSchedulesWorkflow(PostHogWorkflow):
    inputs_cls = ReconcileScannerSchedulesInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: ReconcileScannerSchedulesInputs) -> ReconcileScannerSchedulesResult:
        # Best-effort and first: a schedule-sync failure below must not starve the reapers, and vice versa.
        try:
            await workflow.execute_activity(
                reap_orphaned_observations_activity,
                start_to_close_timeout=REAP_ORPHANED_OBSERVATIONS_TIMEOUT,
                # The activity heartbeats between phases, so a stalled pass is cut loose before it burns
                # the whole tick budget.
                heartbeat_timeout=REAP_ORPHANED_OBSERVATIONS_HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            workflow.logger.exception("replay_vision.reap_orphaned_observations_failed")

        if workflow.patched("reap-stuck-vision-action-runs-2026-07"):
            try:
                await workflow.execute_activity(
                    reap_stuck_vision_action_runs_activity,
                    start_to_close_timeout=REAP_STUCK_VISION_ACTION_RUNS_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception:
                workflow.logger.exception("replay_vision.reap_stuck_vision_action_runs_failed")

        if workflow.patched("reap-childless-inline-scanners-2026-08"):
            try:
                await workflow.execute_activity(
                    reap_childless_inline_scanners_activity,
                    start_to_close_timeout=INLINE_SCANNER_REAP_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception:
                workflow.logger.exception("replay_vision.reap_childless_inline_scanners_failed")

        if workflow.patched("reap-backfill-schedules-2026-08"):
            try:
                await workflow.execute_activity(
                    reap_backfill_schedules_activity,
                    start_to_close_timeout=REAP_BACKFILL_SCHEDULES_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception:
                workflow.logger.exception("replay_vision.reap_backfill_schedules_failed")

        # A scanner toggled between the two listings recovers on the next tick.
        enabled_entries, existing_entries = await asyncio.gather(
            workflow.execute_activity(
                list_enabled_scanners_activity,
                start_to_close_timeout=LIST_ENABLED_SCANNERS_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
            workflow.execute_activity(
                list_scanner_schedules_activity,
                start_to_close_timeout=LIST_SCANNER_SCHEDULES_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )
        enabled = {entry.scanner_id: entry for entry in enabled_entries}
        # Legacy untagged schedules surface as None and naturally drift on first tick.
        existing = {entry.scanner_id: entry.fingerprint for entry in existing_entries}
        drifted = {sid for sid in enabled.keys() & existing.keys() if existing[sid] != enabled[sid].fingerprint}
        to_upsert = sorted((enabled.keys() - existing.keys()) | drifted)
        to_delete = sorted(existing.keys() - enabled.keys())

        upsert_results, delete_results = await asyncio.gather(
            self._fan_out(
                to_upsert,
                lambda sid: workflow.execute_activity(
                    upsert_scanner_schedule_activity,
                    UpsertScannerScheduleActivityInputs(scanner_id=sid, team_id=enabled[sid].team_id),
                    start_to_close_timeout=RECONCILE_SCHEDULE_OP_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                ),
            ),
            self._fan_out(
                to_delete,
                lambda sid: workflow.execute_activity(
                    delete_scanner_schedule_activity,
                    DeleteScannerScheduleActivityInputs(scanner_id=sid),
                    start_to_close_timeout=RECONCILE_SCHEDULE_OP_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                ),
            ),
        )
        result = ReconcileScannerSchedulesResult(
            upserted=[sid for sid, err in zip(to_upsert, upsert_results) if err is None],
            deleted=[sid for sid, err in zip(to_delete, delete_results) if err is None],
            failed_upsert=[sid for sid, err in zip(to_upsert, upsert_results) if err is not None],
            failed_delete=[sid for sid, err in zip(to_delete, delete_results) if err is not None],
        )
        failures = [
            (sid, err) for sid, err in [*zip(to_upsert, upsert_results), *zip(to_delete, delete_results)] if err
        ]
        if failures:
            descriptions = [_describe_failure(sid, err) for sid, err in failures]
            workflow.logger.warning(
                "replay_vision.reconcile_partial_failure",
                extra={"failures": descriptions},
            )
            # A total failure across enough ops points at the schedule backend, not one flaky op — surface it
            # so Temporal retries, and name the scanners and cause so the error is diagnosable.
            attempted = len(to_upsert) + len(to_delete)
            if attempted >= RECONCILER_SYSTEMIC_FAILURE_MIN_OPS and not result.upserted and not result.deleted:
                raise ApplicationError(
                    f"reconciler: all {attempted} schedule ops failed: {', '.join(descriptions)}"
                ) from failures[0][1]
        return result

    async def _fan_out(
        self, scanner_ids: list[UUID], make_coro: Callable[[UUID], Awaitable[None]]
    ) -> list[BaseException | None]:
        if not scanner_ids:
            return []
        # return_exceptions so one scanner's failure doesn't block the others. None marks a success.
        results = await asyncio.gather(*(make_coro(sid) for sid in scanner_ids), return_exceptions=True)
        return [r if isinstance(r, BaseException) else None for r in results]


async def create_replay_vision_reconciler_schedule(client: "Client") -> None:
    """Upsert the global reconciler schedule. Called from worker startup."""
    # Function-local: this module contains `@workflow.defn`, and the Temporal sandbox can't
    # re-import the schedule helper's Django/temporalio.client dependencies when validating the workflow.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=RECONCILER_SCHEDULE_ID,
        workflow_name=RECONCILER_WORKFLOW_NAME,
        workflow_id=RECONCILER_WORKFLOW_ID,
        inputs=ReconcileScannerSchedulesInputs(),
        interval=RECONCILER_INTERVAL,
        execution_timeout=RECONCILER_EXECUTION_TIMEOUT,
    )
