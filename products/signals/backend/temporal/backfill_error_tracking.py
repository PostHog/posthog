import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.facade.contracts import ErrorTrackingIssueImpact

BACKFILL_WINDOW_DAYS = 30
BACKFILL_ISSUE_LIMIT = 5
# The pool holds the newest issues and ranking happens in Python, because a pool cut by users would
# fill with long-running issues that are older than the window, and the backfill would emit nothing.
CANDIDATE_POOL_SIZE = 200
CANDIDATE_LIMIT = 15
MAX_CANDIDATES_PER_SOURCE = 2
MIN_USERS = 2
CRASH_LOOP_OCCURRENCES = 100
SEVERITY_MULTIPLIERS = {"critical": 1.5, "high": 1.25}
TREND_DAYS = 7


@dataclass(frozen=True)
class BackfillErrorTrackingInput:
    team_id: int
    # Only workflow code that stops at BACKFILL_ISSUE_LIMIT asks for spare candidates. Workflow code
    # without that stop emits every candidate it gets, so the default returns no spares.
    candidate_limit: int = BACKFILL_ISSUE_LIMIT


@dataclass(frozen=True)
class ErrorTrackingIssueData:
    issue_id: str
    name: str
    description: str
    fingerprint: str
    # Defaults keep histories from runs that started before these fields existed replayable.
    users: int = 0
    occurrences: int = 0


@dataclass(frozen=True)
class EmitBackfillSignalInput:
    team_id: int
    issue: ErrorTrackingIssueData


def impact_score(issue: ErrorTrackingIssueImpact, now: datetime) -> float:
    """How much fixing this issue matters to the team's users. Only the order of scores is meaningful."""
    # Users count three times as much as occurrences, because one user who hits an error in a
    # loop can produce thousands of occurrences.
    score = 3 * math.log1p(issue.users) + math.log1p(issue.occurrences)
    score *= _recency_multiplier(now - issue.last_seen)
    score *= _trend_multiplier(issue.daily_occurrences)
    score *= SEVERITY_MULTIPLIERS.get(issue.severity or "", 1.0)
    if issue.is_assigned:
        score *= 0.5
    if issue.users <= 1 and issue.occurrences >= CRASH_LOOP_OCCURRENCES:
        score *= 0.5
    return score


def _recency_multiplier(since_last_seen: timedelta) -> float:
    if since_last_seen <= timedelta(days=3):
        return 1.0
    if since_last_seen <= timedelta(days=7):
        return 0.6
    return 0.3


def _trend_multiplier(daily_occurrences: tuple[int, ...]) -> float:
    recent = sum(daily_occurrences[-TREND_DAYS:])
    prior = sum(daily_occurrences[-2 * TREND_DAYS : -TREND_DAYS])
    return 1.25 if recent > 2 * prior else 1.0


def rank_backfill_candidates(
    issues: list[ErrorTrackingIssueImpact], now: datetime, limit: int = CANDIDATE_LIMIT
) -> list[ErrorTrackingIssueImpact]:
    """Issues first seen inside the window that are worth a report, highest impact first."""
    window_start = now - timedelta(days=BACKFILL_WINDOW_DAYS)
    eligible = [
        issue
        for issue in issues
        if issue.first_seen >= window_start
        and (issue.users >= MIN_USERS or (issue.severity or "") in SEVERITY_MULTIPLIERS)
    ]
    eligible.sort(key=lambda issue: (impact_score(issue, now), issue.users), reverse=True)

    ranked: list[ErrorTrackingIssueImpact] = []
    per_source: dict[str, int] = {}
    for issue in eligible:
        if issue.source:
            if per_source.get(issue.source, 0) >= MAX_CANDIDATES_PER_SOURCE:
                continue
            per_source[issue.source] = per_source.get(issue.source, 0) + 1
        ranked.append(issue)
        if len(ranked) >= limit:
            break
    return ranked


@activity.defn
@scoped_temporal()
@close_db_connections
async def fetch_error_tracking_issues_activity(input: BackfillErrorTrackingInput) -> list[ErrorTrackingIssueData]:
    """Fetch new error tracking issues from the last 30 days, ranked by impact on the team's users."""
    from django.utils import timezone

    from posthog.sync import database_sync_to_async

    from products.error_tracking.backend.facade import api as error_tracking_api

    def _fetch() -> list[ErrorTrackingIssueData]:
        candidates = rank_backfill_candidates(
            error_tracking_api.list_active_issue_impact(
                team_id=input.team_id, days=BACKFILL_WINDOW_DAYS, limit=CANDIDATE_POOL_SIZE
            ),
            now=timezone.now(),
            limit=input.candidate_limit,
        )
        if not candidates:
            return []

        first_fingerprints: dict[UUID, str] = {
            fingerprint.issue_id: fingerprint.fingerprint
            for fingerprint in error_tracking_api.list_first_fingerprints(
                team_id=input.team_id, issue_ids=[candidate.id for candidate in candidates]
            )
        }

        return [
            ErrorTrackingIssueData(
                issue_id=str(candidate.id),
                name=candidate.name or "Unknown",
                description=candidate.description or "",
                fingerprint=first_fingerprints.get(candidate.id, ""),
                users=candidate.users,
                occurrences=candidate.occurrences,
            )
            for candidate in candidates
        ]

    return await database_sync_to_async(_fetch)()


@activity.defn
@scoped_temporal()
@close_db_connections
# `None` stays in the hint because histories and workers from before the boolean result return `None`,
# and a `bool` hint makes Temporal fail to decode it on every replay.
async def emit_backfill_signal_activity(input: EmitBackfillSignalInput) -> bool | None:
    """Emit an issue_created signal for a single error tracking issue. Returns whether it was dispatched."""
    from posthog.models import Team

    from products.signals.backend.facade.api import emit_signal

    team = await Team.objects.aget(id=input.team_id)

    description = (
        f"New error tracking issue created - this particular exception was observed for the first time:\n"
        f"{input.issue.name}: {input.issue.description}\n"
    )
    if input.issue.users or input.issue.occurrences:
        description += (
            f"Affected {input.issue.users} users across {input.issue.occurrences} occurrences "
            f"in the last {BACKFILL_WINDOW_DAYS} days.\n"
        )

    return await emit_signal(
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
        stops_at_limit = workflow.patched("backfill-error-tracking-ranked-2026-11")
        issues = await workflow.execute_activity(
            fetch_error_tracking_issues_activity,
            replace(input, candidate_limit=CANDIDATE_LIMIT) if stops_at_limit else input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        emitted = 0
        for issue in issues:
            if stops_at_limit and emitted >= BACKFILL_ISSUE_LIMIT:
                break
            dispatched = await workflow.execute_activity(
                emit_backfill_signal_activity,
                EmitBackfillSignalInput(team_id=input.team_id, issue=issue),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # `None` comes from an old worker, which emitted the signal, so it counts toward the limit.
            if dispatched is not False:
                emitted += 1
