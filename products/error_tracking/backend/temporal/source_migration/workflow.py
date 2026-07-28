import asyncio
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.source_migration.activities import (
        check_warehouse_sync_activity,
        count_imported_fingerprints_activity,
        get_migration_context_activity,
        import_events_activity,
        plan_import_activity,
        set_migration_status_activity,
        sync_issue_status_activity,
    )
    from products.error_tracking.backend.temporal.source_migration.constants import WORKFLOW_NAME
    from products.error_tracking.backend.temporal.source_migration.types import (
        ImportTablesInputs,
        MigrationInputs,
        SetStatusInputs,
    )

DEFAULT_RETRY_POLICY = common.RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))
SHORT_ACTIVITY_TIMEOUT = timedelta(minutes=5)

# The warehouse source syncs on its own schedule; a large org's event fanout can take
# hours, so poll patiently before giving up.
SYNC_POLL_INTERVAL = timedelta(minutes=1)
SYNC_MAX_POLLS = 1440  # 24h

IMPORT_TIMEOUT = timedelta(hours=12)
IMPORT_HEARTBEAT_TIMEOUT = timedelta(minutes=5)
IMPORT_RETRY_POLICY = common.RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=30))

# capture -> Kafka -> cymbal is async; issue rows must exist before status sync
# (cymbal reopens non-active issues on late events).
SETTLE_POLL_INTERVAL = timedelta(seconds=30)
SETTLE_MAX_POLLS = 40

STATUS_SYNC_TIMEOUT = timedelta(hours=1)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingMigrationWorkflow(PostHogWorkflow):
    inputs_cls = MigrationInputs

    @workflow.run
    async def run(self, inputs: MigrationInputs) -> None:
        try:
            await self._run(inputs)
        except asyncio.CancelledError:
            await self._set_status(inputs, "cancelled")
            raise
        except Exception as e:
            await self._set_status(inputs, "failed", error=str(e))
            raise

    async def _run(self, inputs: MigrationInputs) -> None:
        await workflow.execute_activity(
            get_migration_context_activity,
            inputs,
            start_to_close_timeout=SHORT_ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

        sync_check = None
        for _ in range(SYNC_MAX_POLLS):
            sync_check = await workflow.execute_activity(
                check_warehouse_sync_activity,
                inputs,
                start_to_close_timeout=SHORT_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            if sync_check.ready:
                break
            await asyncio.sleep(SYNC_POLL_INTERVAL.total_seconds())
        if sync_check is None or not sync_check.ready:
            reason = sync_check.reason if sync_check else "unknown"
            raise ApplicationError(f"Warehouse schemas never became ready: {reason}")

        tables_inputs = ImportTablesInputs(
            migration_id=inputs.migration_id,
            team_id=inputs.team_id,
            tables=sync_check.tables,
        )

        plan = await workflow.execute_activity(
            plan_import_activity,
            tables_inputs,
            start_to_close_timeout=SHORT_ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

        await workflow.execute_activity(
            import_events_activity,
            tables_inputs,
            start_to_close_timeout=IMPORT_TIMEOUT,
            heartbeat_timeout=IMPORT_HEARTBEAT_TIMEOUT,
            retry_policy=IMPORT_RETRY_POLICY,
        )

        for _ in range(SETTLE_MAX_POLLS):
            fingerprint_count = await workflow.execute_activity(
                count_imported_fingerprints_activity,
                inputs,
                start_to_close_timeout=SHORT_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            if fingerprint_count >= plan.issues_total:
                break
            await asyncio.sleep(SETTLE_POLL_INTERVAL.total_seconds())

        await self._set_status(inputs, "finalizing")

        await workflow.execute_activity(
            sync_issue_status_activity,
            tables_inputs,
            start_to_close_timeout=STATUS_SYNC_TIMEOUT,
            heartbeat_timeout=IMPORT_HEARTBEAT_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

        await self._set_status(inputs, "completed")

    async def _set_status(self, inputs: MigrationInputs, status: str, error: str | None = None) -> None:
        await workflow.execute_activity(
            set_migration_status_activity,
            SetStatusInputs(migration_id=inputs.migration_id, team_id=inputs.team_id, status=status, error=error),
            start_to_close_timeout=SHORT_ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )
