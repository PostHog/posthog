from __future__ import annotations

import datetime as dt

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

from products.managed_warehouse.backend.trino_model_aliases import (
    ModelAliasReconciliation,
    reconcile_trino_model_aliases,
)

logger = structlog.get_logger(__name__)


@frozen
class ModelAliasInputs:
    team_id: int
    pending_ids: tuple[str, ...] = ()
    full_audit: bool = False
    next_audit_at: float = 0
    audit_interval_seconds: float = 1800


@frozen
class ModelAliasBatch:
    team_id: int
    saved_query_ids: tuple[str, ...] | None = None


def _checkpoint() -> None:
    if activity.is_cancelled():
        raise CancelledError()
    if activity.is_worker_shutdown():
        raise RuntimeError("Worker is shutting down")
    activity.heartbeat()


@activity.defn
async def reconcile_trino_model_aliases_activity(inputs: ModelAliasBatch) -> ModelAliasReconciliation:
    from products.managed_warehouse.backend.trino_execution import TrinoQueryControl, run_trino_model

    def execute(control: TrinoQueryControl) -> ModelAliasReconciliation:
        def checkpoint() -> None:
            control.checkpoint()
            _checkpoint()

        return reconcile_trino_model_aliases(inputs.team_id, checkpoint, inputs.saved_query_ids, control)

    async with Heartbeater(details=("model_aliases", inputs.team_id)):
        result = await run_trino_model(execute, query_seconds=5 * 60)
    log = logger.warning if result.errors else logger.info
    log(
        "trino_model_aliases_reconciled",
        team_id=inputs.team_id,
        published=result.published,
        removed=result.removed,
        unchanged=result.unchanged,
        errors=result.errors,
    )
    return result


@workflow.defn(name="managed-warehouse.reconcile-model-aliases")
class ReconcileModelAliasesWorkflow(PostHogWorkflow):
    inputs_cls = ModelAliasInputs

    def __init__(self) -> None:
        self.pending_ids: set[str] = set()
        self.full_audit = False
        self.last_result = ModelAliasReconciliation()

    @workflow.signal
    def refresh(self, saved_query_id: str | None = None) -> None:
        if saved_query_id is None or len(self.pending_ids) >= 1000:
            self.full_audit = True
            self.pending_ids.clear()
        elif not self.full_audit:
            self.pending_ids.add(saved_query_id)

    @workflow.query
    def status(self) -> ModelAliasReconciliation:
        return self.last_result

    @workflow.run
    async def run(self, inputs: ModelAliasInputs) -> None:
        self.pending_ids.update(inputs.pending_ids)
        self.full_audit |= inputs.full_audit
        interval = inputs.audit_interval_seconds
        next_audit = inputs.next_audit_at or (workflow.now().timestamp() + interval)
        if not self.pending_ids and not inputs.next_audit_at:
            self.full_audit = True
        for _ in range(100):
            if not self.pending_ids and not self.full_audit:
                try:
                    await workflow.wait_condition(
                        lambda: bool(self.pending_ids) or self.full_audit,
                        timeout=dt.timedelta(seconds=max(0, next_audit - workflow.now().timestamp())),
                    )
                except TimeoutError:
                    self.full_audit = True
            # Batch bursts before snapshotting IDs; signals during the activity stay queued for the next pass.
            await workflow.sleep(dt.timedelta(seconds=30))
            audit = self.full_audit or workflow.now().timestamp() >= next_audit
            batch = None if audit else tuple(sorted(self.pending_ids)[:100])
            if audit:
                self.pending_ids.clear()
                self.full_audit = False
            else:
                self.pending_ids.difference_update(batch or ())
            try:
                self.last_result = await workflow.execute_activity(
                    reconcile_trino_model_aliases_activity,
                    ModelAliasBatch(team_id=inputs.team_id, saved_query_ids=batch),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=10)),
                )
                if not self.last_result.active and not self.pending_ids and not self.full_audit:
                    return
            except ActivityError as error:
                if isinstance(error.cause, CancelledError):
                    raise error.cause
                self.last_result = ModelAliasReconciliation(errors=(str(error.cause or error)[:1000],))
                self.full_audit |= audit
                self.pending_ids.update(batch or ())
                workflow.logger.warning("Trino model alias reconciliation failed", extra={"team_id": inputs.team_id})
            if audit:
                unchanged = not (self.last_result.published or self.last_result.removed or self.last_result.errors)
                interval = min(interval * 2, 7200) if unchanged else 1800
                next_audit = workflow.now().timestamp() + interval * workflow.random().uniform(0.8, 1.2)
            if self.last_result.errors:
                await workflow.sleep(dt.timedelta(seconds=workflow.random().uniform(60, 120)))
        workflow.continue_as_new(
            ModelAliasInputs(
                team_id=inputs.team_id,
                pending_ids=tuple(sorted(self.pending_ids)),
                full_audit=self.full_audit,
                next_audit_at=next_audit,
                audit_interval_seconds=interval,
            )
        )
