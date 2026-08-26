"""Syncs per-scanner schedules with the ReplayScanner table on every tick, and reaps orphaned observations."""

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    LIST_ENABLED_SCANNERS_TIMEOUT,
    LIST_SCANNER_SCHEDULES_TIMEOUT,
    REAP_BACKFILL_SCHEDULES_HEARTBEAT_TIMEOUT,
    REAP_BACKFILL_SCHEDULES_SCHEDULE_TO_CLOSE,
    REAP_BACKFILL_SCHEDULES_TIMEOUT,
    REAP_ORPHANED_OBSERVATIONS_HEARTBEAT_TIMEOUT,
    REAPER_MAX_ATTEMPTS,
    REAPER_OP_SCHEDULE_TO_CLOSE,
    REAPER_OP_TIMEOUT,
    RECONCILE_SCHEDULE_OP_TIMEOUT,
    RECONCILER_ACTIVITY_PRIORITY,
    RECONCILER_EXECUTION_TIMEOUT,
    RECONCILER_INTERVAL,
    RECONCILER_SCHEDULE_ID,
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
        if workflow.patched("sync-schedules-before-reapers-2026-08"):
            # Schedule sync goes first because it is the only phase a user feels: an enabled scanner
            # that never gets a sweep schedule silently never scans. The reapers only settle rows that
            # are already wrong, so a skipped pass costs one tick. The reapers' combined start-to-close
            # budget is larger than the workflow execution timeout, so running them first lets one slow
            # reaper starve the sync on every tick.
            result, systemic_failure = await self._sync_schedules()
            await self._run_reapers()
        else:
            await self._run_reapers()
            result, systemic_failure = await self._sync_schedules()
        if systemic_failure is not None:
            raise systemic_failure
        return result

    async def _run_reapers(self) -> None:
        # Each reaper is best-effort and isolated: one failure must not stop the others, and none of
        # them may stop schedule sync.
        try:
            await self._run_reaper(
                reap_orphaned_observations_activity,
                heartbeat_timeout=REAP_ORPHANED_OBSERVATIONS_HEARTBEAT_TIMEOUT,
            )
        except Exception:
            workflow.logger.exception("replay_vision.reap_orphaned_observations_failed")

        if workflow.patched("reap-stuck-vision-action-runs-2026-07"):
            try:
                await self._run_reaper(reap_stuck_vision_action_runs_activity)
            except Exception:
                workflow.logger.exception("replay_vision.reap_stuck_vision_action_runs_failed")

        if workflow.patched("reap-childless-inline-scanners-2026-08"):
            try:
                await self._run_reaper(reap_childless_inline_scanners_activity)
            except Exception:
                workflow.logger.exception("replay_vision.reap_childless_inline_scanners_failed")

        if workflow.patched("reap-backfill-schedules-2026-08"):
            try:
                # A full schedule listing outlives the short reaper attempt, so this one keeps a long
                # attempt and leans on heartbeats to detect a dead worker.
                await self._run_reaper(
                    reap_backfill_schedules_activity,
                    heartbeat_timeout=REAP_BACKFILL_SCHEDULES_HEARTBEAT_TIMEOUT,
                    start_to_close_timeout=REAP_BACKFILL_SCHEDULES_TIMEOUT,
                    schedule_to_close_timeout=REAP_BACKFILL_SCHEDULES_SCHEDULE_TO_CLOSE,
                )
            except Exception:
                workflow.logger.exception("replay_vision.reap_backfill_schedules_failed")

    async def _sync_schedules(self) -> tuple[ReconcileScannerSchedulesResult, ApplicationError | None]:
        """Converge per-scanner schedules with the table. Returns the result plus a systemic failure to
        raise once the rest of the tick is done."""
        # A scanner toggled between the two listings recovers on the next tick.
        enabled_entries, existing_entries = await asyncio.gather(
            workflow.execute_activity(
                list_enabled_scanners_activity,
                start_to_close_timeout=LIST_ENABLED_SCANNERS_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
                priority=RECONCILER_ACTIVITY_PRIORITY,
            ),
            workflow.execute_activity(
                list_scanner_schedules_activity,
                start_to_close_timeout=LIST_SCANNER_SCHEDULES_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
                priority=RECONCILER_ACTIVITY_PRIORITY,
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
                    priority=RECONCILER_ACTIVITY_PRIORITY,
                ),
            ),
            self._fan_out(
                to_delete,
                lambda sid: workflow.execute_activity(
                    delete_scanner_schedule_activity,
                    DeleteScannerScheduleActivityInputs(scanner_id=sid),
                    start_to_close_timeout=RECONCILE_SCHEDULE_OP_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    priority=RECONCILER_ACTIVITY_PRIORITY,
                ),
            ),
        )
        result = ReconcileScannerSchedulesResult(
            upserted=[sid for sid, ok in zip(to_upsert, upsert_results) if ok],
            deleted=[sid for sid, ok in zip(to_delete, delete_results) if ok],
            failed_upsert=[sid for sid, ok in zip(to_upsert, upsert_results) if not ok],
            failed_delete=[sid for sid, ok in zip(to_delete, delete_results) if not ok],
        )
        if result.failed_upsert or result.failed_delete:
            workflow.logger.warning(
                "replay_vision.reconcile_partial_failure",
                extra={
                    "failed_upsert": [str(s) for s in result.failed_upsert],
                    "failed_delete": [str(s) for s in result.failed_delete],
                },
            )
        # Total failure across both fan-outs is likely systemic — surface it so Temporal retries.
        attempted = len(to_upsert) + len(to_delete)
        succeeded = len(result.upserted) + len(result.deleted)
        if attempted > 0 and succeeded == 0:
            return result, ApplicationError(f"reconciler: all {attempted} fan-out activities failed")
        return result, None

    async def _run_reaper(
        self,
        reaper_activity: Callable[[], Any],
        *,
        heartbeat_timeout: dt.timedelta | None = None,
        start_to_close_timeout: dt.timedelta = REAPER_OP_TIMEOUT,
        schedule_to_close_timeout: dt.timedelta = REAPER_OP_SCHEDULE_TO_CLOSE,
    ) -> None:
        await workflow.execute_activity(
            reaper_activity,
            start_to_close_timeout=start_to_close_timeout,
            schedule_to_close_timeout=schedule_to_close_timeout,
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=RetryPolicy(maximum_attempts=REAPER_MAX_ATTEMPTS),
            priority=RECONCILER_ACTIVITY_PRIORITY,
        )

    async def _fan_out(self, scanner_ids: list[UUID], make_coro: Callable[[UUID], Awaitable[None]]) -> list[bool]:
        if not scanner_ids:
            return []
        # return_exceptions so one scanner's failure doesn't block the others.
        results = await asyncio.gather(*(make_coro(sid) for sid in scanner_ids), return_exceptions=True)
        return [not isinstance(r, BaseException) for r in results]


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
