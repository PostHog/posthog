import asyncio
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.auto_resolve.activities import (
        list_auto_resolve_teams,
        resolve_quiet_issues,
        sync_pending_auto_resolves,
    )

WORKFLOW_NAME = "error-tracking-auto-resolve"
TEAM_CONCURRENCY = 4
RETRY = common.RetryPolicy(maximum_attempts=3)


@frozen
class AutoResolveInputs:
    dry_run: bool = False
    sync_only: bool = False


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingAutoResolveWorkflow(PostHogWorkflow):
    inputs_cls = AutoResolveInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: AutoResolveInputs | None = None) -> None:
        inputs = inputs or AutoResolveInputs()
        team_ids = await workflow.execute_activity(
            list_auto_resolve_teams,
            inputs.sync_only,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RETRY,
        )

        async def process_team(team_id: int) -> None:
            if not inputs.sync_only:
                await workflow.execute_activity(
                    resolve_quiet_issues,
                    args=[team_id, inputs.dry_run],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RETRY,
                )
            if not inputs.dry_run:
                await workflow.execute_activity(
                    sync_pending_auto_resolves,
                    team_id,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RETRY,
                )

        failed = 0
        for start in range(0, len(team_ids), TEAM_CONCURRENCY):
            batch = team_ids[start : start + TEAM_CONCURRENCY]
            results = await asyncio.gather(*(process_team(team_id) for team_id in batch), return_exceptions=True)
            for team_id, result in zip(batch, results, strict=True):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    failed += 1
                    workflow.logger.error("error_tracking.auto_resolve.team_failed", extra={"team_id": team_id})
        if failed:
            raise ApplicationError(f"Auto-resolve failed for {failed} projects", non_retryable=True)
