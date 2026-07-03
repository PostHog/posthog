import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

if TYPE_CHECKING:
    from posthog.models import Team

# Experiment gating which order the backfill fetches issues in.
SIGNALS_ET_BACKFILL_SORT_FLAG = "signals-et-backfill-sort"

# Number of issues to seed the Signals inbox with on backfill.
BACKFILL_ISSUE_LIMIT = 10

# Issue sort orders (ErrorTrackingQuery.orderBy values), both applied DESC.
ORDER_BY_RECENCY = "first_seen"  # control: most recently first-seen issues
ORDER_BY_USERS_IMPACTED = "users"  # test: issues impacting the most distinct users


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


def _backfill_order_by(team: "Team") -> str:
    """Pick the backfill sort order for this team from the experiment variant.

    The experiment is aggregated at the project (team) level, so the flag is
    evaluated with the team's group — keyed the same way (`team.uuid`) as the
    `pr_merged` events the experiment measures. Control (or an unavailable flag
    service) keeps recency ordering; the test variant ranks issues by the number
    of distinct users impacted. Evaluating the flag also records the team's
    experiment exposure via `$feature_flag_called`.
    """
    from posthog.event_usage import groups

    variant = posthoganalytics.get_feature_flag(
        SIGNALS_ET_BACKFILL_SORT_FLAG,
        str(team.uuid),
        groups=groups(team=team),
    )
    return ORDER_BY_USERS_IMPACTED if variant == "test" else ORDER_BY_RECENCY


def _fetch_issues_ordered_by(team: "Team", order_by: str) -> list[ErrorTrackingIssueData]:
    """Fetch the top BACKFILL_ISSUE_LIMIT issues for a team, ordered by `order_by` DESC."""
    from posthog.schema import DateRange, ErrorTrackingQuery

    from products.error_tracking.backend.facade.queries import ErrorTrackingQueryRunner

    runner = ErrorTrackingQueryRunner(
        team=team,
        query=ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            dateRange=DateRange(),
            orderBy=order_by,
            orderDirection="DESC",
            volumeResolution=1,
            limit=BACKFILL_ISSUE_LIMIT,
            withFirstEvent=True,
            withAggregations=False,
        ),
    )
    response = runner.calculate()

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
@scoped_temporal()
@close_db_connections
async def fetch_error_tracking_issues_activity(input: BackfillErrorTrackingInput) -> list[ErrorTrackingIssueData]:
    """Fetch the issues to backfill, ordered per the team's experiment variant."""
    from posthog.models import Team
    from posthog.sync import database_sync_to_async

    team = await Team.objects.aget(id=input.team_id)
    order_by = await database_sync_to_async(_backfill_order_by)(team)
    return await database_sync_to_async(_fetch_issues_ordered_by)(team, order_by)


@activity.defn
@scoped_temporal()
@close_db_connections
async def emit_backfill_signal_activity(input: EmitBackfillSignalInput) -> None:
    """Emit an issue_created signal for a single error tracking issue."""
    from posthog.models import Team

    from products.signals.backend.facade.api import emit_signal

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
        with posthoganalytics.new_context(capture_exceptions=False):
            posthoganalytics.tag("team_id", input.team_id)
            posthoganalytics.tag("product", "signals")
            await self._run_impl(input)

    async def _run_impl(self, input: BackfillErrorTrackingInput) -> None:
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
