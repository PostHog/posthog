from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

BACKFILL_WINDOW_DAYS = 30
BACKFILL_ISSUE_LIMIT = 5


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
@scoped_temporal()
@close_db_connections
async def fetch_error_tracking_issues_activity(input: BackfillErrorTrackingInput) -> list[ErrorTrackingIssueData]:
    """Fetch the most recently created error tracking issues from the last 30 days."""
    from django.utils import timezone

    from posthog.sync import database_sync_to_async

    from products.error_tracking.backend.facade import api as error_tracking_api

    def _fetch() -> list[ErrorTrackingIssueData]:
        # Issue metadata and fingerprints both live in Postgres, so the backfill reads them
        # directly instead of scanning events. The previous events scan also misattributed
        # old issues with recent occurrences as newly created, and missed imported issues
        # whose event timestamps predate the window.
        previews = error_tracking_api.list_issues_created_since(
            team_id=input.team_id,
            since=timezone.now() - timedelta(days=BACKFILL_WINDOW_DAYS),
            limit=BACKFILL_ISSUE_LIMIT,
        )
        if not previews:
            return []

        # Bulk-fetch fingerprints and keep the earliest per issue (queryset is created_at-ordered).
        first_fingerprints: dict[UUID, str] = {}
        for fingerprint in error_tracking_api.list_fingerprints(
            team_id=input.team_id, issue_ids=[preview.id for preview in previews]
        ):
            first_fingerprints.setdefault(fingerprint.issue_id, fingerprint.fingerprint)

        return [
            ErrorTrackingIssueData(
                issue_id=str(preview.id),
                name=preview.name or "Unknown",
                description=preview.description or "",
                fingerprint=first_fingerprints.get(preview.id, ""),
            )
            for preview in previews
        ]

    return await database_sync_to_async(_fetch)()


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
