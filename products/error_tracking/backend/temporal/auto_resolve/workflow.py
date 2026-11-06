from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.auto_resolve.activities import (
        auto_resolve_teams_activity,
        get_auto_resolve_team_batches_activity,
    )
    from products.error_tracking.backend.temporal.auto_resolve.types import (
        AutoResolveInputs,
        AutoResolveResult,
        AutoResolveTeamsInputs,
    )

WORKFLOW_NAME = "error-tracking-auto-resolve"

SELECT_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))
SELECT_TIMEOUT = timedelta(minutes=5)

# A retried batch only resolves what is still quiet and active, so a second attempt cannot double-resolve.
BATCH_RETRY_POLICY = common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))
BATCH_START_TO_CLOSE_TIMEOUT = timedelta(hours=1)
BATCH_HEARTBEAT_TIMEOUT = timedelta(minutes=10)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingAutoResolveWorkflow(PostHogWorkflow):
    inputs_cls = AutoResolveInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: AutoResolveInputs | None = None) -> AutoResolveResult:
        if inputs is None:
            inputs = AutoResolveInputs()

        batches = await workflow.execute_activity(
            get_auto_resolve_team_batches_activity,
            inputs,
            start_to_close_timeout=SELECT_TIMEOUT,
            retry_policy=SELECT_RETRY_POLICY,
        )

        teams_total = 0
        teams_failed = 0
        issues_resolved = 0
        # One batch at a time keeps the Postgres write load of the run flat.
        for batch in batches:
            try:
                result = await workflow.execute_activity(
                    auto_resolve_teams_activity,
                    AutoResolveTeamsInputs(team_ids=batch),
                    start_to_close_timeout=BATCH_START_TO_CLOSE_TIMEOUT,
                    heartbeat_timeout=BATCH_HEARTBEAT_TIMEOUT,
                    retry_policy=BATCH_RETRY_POLICY,
                )
            except Exception as error:
                teams_failed += len(batch)
                workflow.logger.warning("error_tracking.auto_resolve.batch_failed", extra={"error": str(error)})
                continue
            teams_total += result.teams_processed
            teams_failed += result.teams_failed
            issues_resolved += result.issues_resolved

        return AutoResolveResult(teams_total=teams_total, teams_failed=teams_failed, issues_resolved=issues_resolved)
