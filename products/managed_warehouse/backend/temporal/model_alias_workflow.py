from __future__ import annotations

import datetime as dt

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync

from products.managed_warehouse.backend.trino_model_aliases import (
    ModelAliasReconciliation,
    reconcile_trino_model_aliases,
)

logger = structlog.get_logger(__name__)


@frozen
class ModelAliasInputs:
    team_id: int


def _checkpoint() -> None:
    if activity.is_cancelled():
        raise CancelledError()
    if activity.is_worker_shutdown():
        raise RuntimeError("Worker is shutting down")
    activity.heartbeat()


@activity.defn
def reconcile_trino_model_aliases_activity(inputs: ModelAliasInputs) -> ModelAliasReconciliation:
    with HeartbeaterSync(details=("model_aliases", inputs.team_id), logger=logger):
        result = reconcile_trino_model_aliases(inputs.team_id, _checkpoint)
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
        self.refresh_requested = False
        self.last_result = ModelAliasReconciliation()

    @workflow.signal
    def refresh(self) -> None:
        self.refresh_requested = True

    @workflow.query
    def status(self) -> ModelAliasReconciliation:
        return self.last_result

    @workflow.run
    async def run(self, inputs: ModelAliasInputs) -> None:
        for _ in range(100):
            self.refresh_requested = False
            try:
                self.last_result = await workflow.execute_activity(
                    reconcile_trino_model_aliases_activity,
                    inputs,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=10)),
                )
            except ActivityError as error:
                if isinstance(error.cause, CancelledError):
                    raise error.cause
                self.last_result = ModelAliasReconciliation(errors=(str(error.cause or error)[:1000],))
                workflow.logger.warning("Trino model alias reconciliation failed", extra={"team_id": inputs.team_id})
            try:
                await workflow.wait_condition(lambda: self.refresh_requested, timeout=dt.timedelta(minutes=5))
            except TimeoutError:
                pass
        # Periodic reconciliation also repairs renames/deletions without a subsequent model build.
        workflow.continue_as_new(inputs)
