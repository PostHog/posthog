import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy


@dataclass
class BackfillErrorTrackingInput:
    team_id: int


@dataclass
class ErrorTrackingIssueData:
    issue_id: str
    name: str
    description: str
    fingerprint: str


@dataclass
class EmitBackfillSignalInput:
    team_id: int
    issue: ErrorTrackingIssueData


@activity.defn
async def fetch_error_tracking_issues_activity(input: BackfillErrorTrackingInput) -> list[ErrorTrackingIssueData]:
    """Fetch the 100 most recent error tracking issues ordered by first seen."""
    from posthog.schema import DateRange, ErrorTrackingQuery

    from posthog.models import Team
    from posthog.sync import database_sync_to_async

    from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

    team = await Team.objects.aget(id=input.team_id)

    def _run_query():
        runner = ErrorTrackingQueryRunner(
            team=team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                orderBy="first_seen",
                orderDirection="DESC",
                volumeResolution=1,
                limit=100,
                useQueryV2=False,
                withFirstEvent=True,
                withAggregations=False,
            ),
        )
        return runner.calculate()

    response = await database_sync_to_async(_run_query)()

    issues: list[ErrorTrackingIssueData] = []
    for result in response.results:
        fingerprint = ""
        if result.first_event and result.first_event.properties:
            try:
                props = (
                    json.loads(result.first_event.properties)
                    if isinstance(result.first_event.properties, str)
                    else result.first_event.properties
                )
                fp = props.get("$exception_fingerprint", "")
                fingerprint = fp if isinstance(fp, str) else str(fp)
            except (json.JSONDecodeError, AttributeError):
                pass

        issues.append(
            ErrorTrackingIssueData(
                issue_id=result.id,
                name=result.name or "Unknown",
                description=result.description or "",
                fingerprint=fingerprint,
            )
        )

    return issues


@activity.defn
async def emit_backfill_signal_activity(input: EmitBackfillSignalInput) -> None:
    """Emit an issue_created signal for a single error tracking issue."""
    from posthog.models import Team

    from products.signals.backend.api import emit_signal

    team = await Team.objects.aget(id=input.team_id)

    description = (
        f"New error tracking issue created - this particular exception was observed for the first time:\n"
        f"{input.issue.name}: {input.issue.description}\n"
    )

    await emit_signal(
        team=team,
        source_product="error_tracking",
        source_type="issue_created",
        source_id=input.issue.issue_id,
        description=description,
        weight=1.0,
        extra={"fingerprint": input.issue.fingerprint},
    )


@workflow.defn(name="backfill-error-tracking")
class BackfillErrorTrackingWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"backfill-error-tracking-{team_id}"

    @workflow.run
    async def run(self, input: BackfillErrorTrackingInput) -> None:
        issues = await workflow.execute_activity(
            fetch_error_tracking_issues_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        for issue in issues:
            await workflow.execute_activity(
                emit_backfill_signal_activity,
                EmitBackfillSignalInput(team_id=input.team_id, issue=issue),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
