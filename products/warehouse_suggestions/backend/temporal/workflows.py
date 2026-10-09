import asyncio
import datetime as dt
import dataclasses

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import generate_warehouse_suggestions, get_warehouse_suggestion_team_batches
from .contracts import WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME, BatchOutcome, WarehouseSuggestionsInputs

RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=dt.timedelta(minutes=5),
)


@workflow.defn(name=WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME)
class WarehouseSuggestionsWorkflow(PostHogWorkflow):
    inputs_cls = WarehouseSuggestionsInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: WarehouseSuggestionsInputs) -> BatchOutcome:
        batches = await workflow.execute_activity(
            get_warehouse_suggestion_team_batches,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RETRY_POLICY,
        )
        semaphore = asyncio.Semaphore(inputs.max_concurrent)
        run_id = workflow.info().run_id

        async def run_batch(team_ids: list[int]) -> BatchOutcome:
            async with semaphore:
                return await workflow.execute_activity(
                    generate_warehouse_suggestions,
                    args=[team_ids, run_id],
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    heartbeat_timeout=dt.timedelta(minutes=5),
                    retry_policy=RETRY_POLICY,
                )

        outcomes = await asyncio.gather(*(run_batch(batch) for batch in batches), return_exceptions=True)
        total = BatchOutcome()
        for batch, outcome in zip(batches, outcomes):
            if isinstance(outcome, BaseException):
                outcome = BatchOutcome(failed=len(batch))
            total = BatchOutcome(
                **{
                    field.name: getattr(total, field.name) + getattr(outcome, field.name)
                    for field in dataclasses.fields(BatchOutcome)
                }
            )
        return total
