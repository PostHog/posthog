import asyncio
import dataclasses
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.logic.issue_tags.sweep import QUERY_MAX_EXECUTION_SECONDS
    from products.error_tracking.backend.temporal.tag_rule_sweep.activities import (
        list_tag_rule_teams_activity,
        sweep_team_tag_rules_activity,
    )
    from products.error_tracking.backend.temporal.tag_rule_sweep.types import (
        SweepTeamTagRulesInputs,
        SweepTeamTagRulesResult,
        TagRuleSweepInputs,
        TagRuleSweepResult,
    )

WORKFLOW_NAME = "error-tracking-tag-rule-sweep"

FAILED_TEAMS_ERROR_TYPE = "ErrorTrackingTagRuleSweepTeamsFailed"

# The schedule runs once a day. The window starts an hour before the previous run's window ended, so that an exception
# that arrives up to an hour late, or a run that starts up to an hour late, is still read. An exception that arrives
# later than that can fall between two windows.
SWEEP_WINDOW = timedelta(hours=25)

LIST_TEAMS_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
LIST_TEAMS_TIMEOUT = timedelta(minutes=5)

SWEEP_TEAM_START_TO_CLOSE_TIMEOUT = timedelta(minutes=30)
# The activity heartbeats after the query and after each label write, so the query can run to its time limit with no
# heartbeat.
SWEEP_TEAM_HEARTBEAT_TIMEOUT = timedelta(seconds=QUERY_MAX_EXECUTION_SECONDS * 2)
# The retry budget must outlast a ClickHouse capacity incident, because every attempt made during one fails the same
# way. These values give 5s, 20s, 80s, 320s, then 600s per retry, so the 8 attempts spread across about 37 minutes.
SWEEP_TEAM_RETRY_POLICY = common.RetryPolicy(
    maximum_attempts=8,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=4.0,
    maximum_interval=timedelta(minutes=10),
)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingTagRuleSweepWorkflow(PostHogWorkflow):
    """Labels each issue with an exception of the last day that matches a tag rule.

    The issue-created tagger reads only an issue's first exception, so this sweep labels an issue whose later
    exceptions match. A team that fails does not stop the other teams, and the run fails once at the end.
    """

    inputs_cls = TagRuleSweepInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: TagRuleSweepInputs | None = None) -> TagRuleSweepResult:
        if inputs is None:
            inputs = TagRuleSweepInputs()
        if inputs.max_concurrent_teams < 1:
            raise ApplicationError(
                f"max_concurrent_teams must be at least 1, got {inputs.max_concurrent_teams}", non_retryable=True
            )

        end = workflow.now()
        start = end - SWEEP_WINDOW
        team_ids = await workflow.execute_activity(
            list_tag_rule_teams_activity,
            start_to_close_timeout=LIST_TEAMS_TIMEOUT,
            retry_policy=LIST_TEAMS_RETRY_POLICY,
        )

        semaphore = asyncio.Semaphore(inputs.max_concurrent_teams)

        async def sweep_team(team_id: int) -> SweepTeamTagRulesResult:
            async with semaphore:
                return await workflow.execute_activity(
                    sweep_team_tag_rules_activity,
                    SweepTeamTagRulesInputs(team_id=team_id, start=start, end=end, dry_run=inputs.dry_run),
                    start_to_close_timeout=SWEEP_TEAM_START_TO_CLOSE_TIMEOUT,
                    heartbeat_timeout=SWEEP_TEAM_HEARTBEAT_TIMEOUT,
                    retry_policy=SWEEP_TEAM_RETRY_POLICY,
                )

        results = await asyncio.gather(*(sweep_team(team_id) for team_id in team_ids), return_exceptions=True)

        swept: list[SweepTeamTagRulesResult] = []
        teams_failed = 0
        for team_id, result in zip(team_ids, results):
            # Workflow cancellation lands here as a captured CancelledError. Counting it as a failed team would keep
            # the run going instead of honoring the cancel.
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                teams_failed += 1
                workflow.logger.error(
                    "error_tracking_tag_rule_sweep_team_failed", extra={"team_id": team_id, "error": str(result)}
                )
                continue
            swept.append(result)

        summary = TagRuleSweepResult(
            teams=len(team_ids),
            teams_skipped=sum(1 for result in swept if result.skipped is not None),
            teams_failed=teams_failed,
            rules_run=sum(result.rules_run for result in swept),
            rules_skipped=sum(result.rules_skipped for result in swept),
            matching_issues=sum(result.matching_issues for result in swept),
            labels_to_write=sum(result.labels_to_write for result in swept),
            labels_written=sum(result.labels_written for result in swept),
        )
        workflow.logger.info(
            "error_tracking_tag_rule_sweep_complete",
            extra={
                **dataclasses.asdict(summary),
                "teams_truncated": sum(1 for result in swept if result.truncated),
            },
        )

        if teams_failed:
            workflow.metric_meter().create_counter(
                "error_tracking_tag_rule_sweep_teams_failed",
                "Teams whose daily tag rule sweep failed after its retries",
            ).add(teams_failed)
            raise ApplicationError(
                f"Error Tracking tag rule sweep failed for {teams_failed}/{summary.teams} teams",
                type=FAILED_TEAMS_ERROR_TYPE,
                non_retryable=True,
            )

        return summary
