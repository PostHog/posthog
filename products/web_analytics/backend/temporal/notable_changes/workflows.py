import asyncio
from datetime import datetime, timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from products.web_analytics.backend.temporal.notable_changes.activities import get_eligible_team_ids, process_team_batch
from products.web_analytics.backend.temporal.notable_changes.types import (
    ProcessTeamBatchInput,
    WebNotableChangesCoordinatorInput,
)


@workflow.defn(name="web-notable-changes-coordinator")
class WebNotableChangesCoordinatorWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> WebNotableChangesCoordinatorInput:
        if input:
            raise ValueError(f"WebNotableChangesCoordinatorWorkflow does not accept CLI args, got: {input}")
        return WebNotableChangesCoordinatorInput()

    @workflow.run
    async def run(self, input: WebNotableChangesCoordinatorInput) -> None:
        now = workflow.now()
        year, week, _ = now.isocalendar()
        week_key = f"{year}-W{week:02d}"
        week_start_iso = datetime.fromisocalendar(year, week, 1).date().isoformat()

        team_ids = await workflow.execute_activity(
            get_eligible_team_ids,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=2),
        )

        if not team_ids:
            return

        batches = [team_ids[i : i + input.batch_size] for i in range(0, len(team_ids), input.batch_size)]

        results = await asyncio.gather(
            *[
                workflow.execute_activity(
                    process_team_batch,
                    ProcessTeamBatchInput(
                        team_ids=batch,
                        week_key=week_key,
                        week_start_iso=week_start_iso,
                        limit_per_team=input.limit_per_team,
                    ),
                    start_to_close_timeout=timedelta(hours=1),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=common.RetryPolicy(maximum_attempts=2),
                )
                for batch in batches
            ],
            return_exceptions=True,
        )

        failures = [(i, r) for i, r in enumerate(results) if isinstance(r, BaseException)]
        for i, result in failures:
            workflow.logger.error(f"Batch {i} failed: {result}")

        if len(failures) == len(results):
            raise ApplicationError(
                f"All {len(results)} notable-changes batches failed",
                non_retryable=True,
            )
