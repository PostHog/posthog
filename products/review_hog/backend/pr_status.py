"""Where a pull request's ReviewHog runs stand, and how one trigger request ended.

Agents poll this after `review-hog-reviews-trigger`. The database answers first: in-flight turns,
resolution runs, completed turns (`turn_marker` rows) and the run outcome notes of failed or
skipped runs. Temporal is asked only to tell `queued` from `idle` when the database shows nothing
running, and a failed probe reads as `unknown`, never `idle`.
"""

from datetime import datetime, timedelta

from django.db import models

from posthog.dataclasses import frozen

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.requested_reviews import RUN_MODE_FLASH, RUN_MODE_RESOLVE_ONLY
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL, effective_priority
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_findings_bundle
from products.review_hog.backend.reviewer.progress import (
    RESOLUTION_COMPLETED,
    RESOLUTION_RESOLVING,
    RESOLUTION_STOPPED,
    RUN_OUTCOME_FAILED,
    RUN_STAGE_RESOLUTION,
    RUN_STAGE_REVIEW,
    ResolutionSummary,
    RunOutcomeMarker,
    in_progress_report_ids,
    latest_resolution_summaries,
    resolution_states,
    run_outcome_markers,
    turn_markers,
)
from products.review_hog.backend.temporal.client import WorkflowProbe, probe_workflow
from products.review_hog.backend.temporal.types import resolve_pr_workflow_id, review_pr_workflow_id


class ReviewPRState(models.TextChoices):
    NOT_REVIEWED = "not_reviewed", "Not reviewed"
    QUEUED = "queued", "Queued"
    REVIEWING = "reviewing", "Reviewing"
    RESOLVING = "resolving", "Resolving"
    IDLE = "idle", "Idle"
    UNKNOWN = "unknown", "Unknown"


class ReviewRequestOutcomeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    SKIPPED = "skipped", "Skipped"
    FAILED = "failed", "Failed"
    UNKNOWN = "unknown", "Unknown"


NO_MATCHING_RUN_REASON = "no_matching_run"
STOPPED_REASON = "stopped"

_RUNNING_STATES = (ReviewPRState.QUEUED, ReviewPRState.REVIEWING, ReviewPRState.RESOLVING)
# Agents poll this endpoint, so a slow Temporal answer must not hold the request open.
_PROBE_RPC_TIMEOUT = timedelta(seconds=2)


@frozen
class LatestReview:
    review_id: str
    review_mode: str | None
    head_sha: str | None
    run_index: int
    completed_at: datetime | None
    must_fix_count: int
    should_fix_count: int
    consider_count: int
    turn_published: bool
    status_comment_url: str | None


@frozen
class RequestOutcome:
    status: ReviewRequestOutcomeStatus
    reason: str | None = None
    review_id: str | None = None
    run_index: int | None = None


@frozen
class PRStatus:
    repository: str
    pr_number: int
    report_id: str | None
    state: ReviewPRState
    latest_review: LatestReview | None
    latest_resolution: ResolutionSummary | None
    request_outcome: RequestOutcome | None


def _covers(turn_mode: str, requested_mode: str) -> bool:
    """A Deep turn answers a Standard request too, because no Standard review runs after a Deep one."""
    return turn_mode == requested_mode or turn_mode == REVIEW_MODE_FULL


def _resolution_answers(resolution: ResolutionSummary, requested_at: datetime) -> bool:
    """Whether this resolution run can be the one the request started or joined.

    A `resolve_only` request joins a resolution that already runs, so a run that started earlier
    answers it while it still runs, or when it completed at or after the request.
    """
    if resolution.started_at >= requested_at or resolution.status == RESOLUTION_RESOLVING:
        return True
    return resolution.completed_at is not None and resolution.completed_at >= requested_at


class PRStatusLookup:
    """One pull request's status on the root team, read in one pass."""

    def __init__(self, team_id: int, owner: str, repo: str, pr_number: int) -> None:
        self.team_id = team_id
        self.owner = owner
        self.repo = repo
        self.pr_number = pr_number
        self.repository = f"{owner}/{repo}"
        # Repository casing can differ per trigger, so match it the way the trigger does.
        self.report = (
            ReviewReport.objects.for_team(team_id, canonical=True)
            .filter(repository__iexact=self.repository, pr_number=pr_number)
            .first()
        )
        self.report_id = str(self.report.id) if self.report is not None else None

    def _probe(self) -> WorkflowProbe:
        review = probe_workflow(
            review_pr_workflow_id(team_id=self.team_id, owner=self.owner, repo=self.repo, pr_number=self.pr_number),
            rpc_timeout=_PROBE_RPC_TIMEOUT,
        )
        if review == WorkflowProbe.RUNNING:
            return review
        resolve = probe_workflow(
            resolve_pr_workflow_id(team_id=self.team_id, owner=self.owner, repo=self.repo, pr_number=self.pr_number),
            rpc_timeout=_PROBE_RPC_TIMEOUT,
        )
        if resolve == WorkflowProbe.RUNNING:
            return resolve
        if WorkflowProbe.UNKNOWN in (review, resolve):
            return WorkflowProbe.UNKNOWN
        return WorkflowProbe.NOT_RUNNING

    def _state(self) -> ReviewPRState:
        report = self.report
        if report is not None and self.report_id is not None:
            live_resolution = resolution_states(self.team_id, [report]).get(self.report_id)
            if live_resolution is not None and live_resolution.status == RESOLUTION_RESOLVING:
                return ReviewPRState.RESOLVING
            if self.report_id in in_progress_report_ids(self.team_id, [report]):
                return ReviewPRState.REVIEWING
        probe = self._probe()
        if probe == WorkflowProbe.RUNNING:
            return ReviewPRState.QUEUED
        if probe == WorkflowProbe.UNKNOWN:
            return ReviewPRState.UNKNOWN
        if report is None or report.run_count == 0:
            return ReviewPRState.NOT_REVIEWED
        return ReviewPRState.IDLE

    def _latest_review(self) -> LatestReview | None:
        report = self.report
        if report is None or self.report_id is None or report.run_count == 0:
            return None
        report_id = self.report_id
        pairs = load_findings_bundle(team_id=self.team_id, report_ids=[report_id]).turn(report_id, report.run_count)
        counts = dict.fromkeys(IssuePriority, 0)
        for finding, verdict in pairs:
            if verdict is not None and verdict.is_valid:
                counts[effective_priority(finding.priority, verdict.adjusted_priority)] += 1
        marker = turn_markers(self.team_id, [report_id]).get((report_id, report.run_count))
        return LatestReview(
            review_id=report_id,
            review_mode=marker.review_mode if marker else None,
            head_sha=report.completed_head_sha or report.head_sha,
            run_index=report.run_count,
            completed_at=report.last_run_at,
            must_fix_count=counts[IssuePriority.MUST_FIX],
            should_fix_count=counts[IssuePriority.SHOULD_FIX],
            consider_count=counts[IssuePriority.CONSIDER],
            turn_published=str(report.run_count) in (report.published_head_shas or {}),
            status_comment_url=f"{report.pr_url}#issuecomment-{report.status_comment_id}"
            if report.pr_url and report.status_comment_id
            else None,
        )

    def _completed_turn(self, requested_at: datetime, requested_mode: str) -> int | None:
        """The newest completed turn that answers the request, if any."""
        report = self.report
        if report is None or self.report_id is None:
            return None
        markers = turn_markers(self.team_id, [self.report_id])
        for run_index in range(report.run_count, 0, -1):
            marker = markers.get((self.report_id, run_index))
            if marker is None or not _covers(marker.review_mode, requested_mode):
                continue
            # The latest turn's finish time is `last_run_at`. Older turns store no finish time, but a
            # turn whose marker was written after the request also finished after it.
            if run_index == report.run_count and report.last_run_at is not None:
                finished_after_request = report.last_run_at >= requested_at
            else:
                finished_after_request = marker.started_at >= requested_at
            if finished_after_request:
                return run_index
        return None

    def _ended_outcome(self, marker: RunOutcomeMarker, state: ReviewPRState) -> RequestOutcome:
        """A failed or skipped run ends the request only when nothing runs, because the queue can retry it."""
        if state in _RUNNING_STATES:
            return RequestOutcome(status=ReviewRequestOutcomeStatus.PENDING, review_id=self.report_id)
        if state == ReviewPRState.UNKNOWN:
            return RequestOutcome(status=ReviewRequestOutcomeStatus.UNKNOWN, review_id=self.report_id)
        return RequestOutcome(
            status=ReviewRequestOutcomeStatus(marker.outcome),
            reason=marker.reason,
            review_id=self.report_id,
            run_index=marker.run_index,
        )

    def _review_outcome(
        self, requested_at: datetime, requested_mode: str, state: ReviewPRState
    ) -> RequestOutcome | None:
        if self.report is None or self.report_id is None:
            return None
        review_markers = [
            marker
            for marker in run_outcome_markers(self.team_id, [self.report_id], since=requested_at)[self.report_id]
            if marker.stage == RUN_STAGE_REVIEW
        ]
        run_index = self._completed_turn(requested_at, requested_mode)
        if run_index is not None:
            # Finalize counts the turn before it publishes, so a publish failure marks the same turn failed.
            turn_failed = [
                marker
                for marker in review_markers
                if marker.outcome == RUN_OUTCOME_FAILED and marker.run_index == run_index
            ]
            if turn_failed:
                return self._ended_outcome(turn_failed[-1], state)
            if run_index == self.report.run_count and state == ReviewPRState.REVIEWING:
                return RequestOutcome(status=ReviewRequestOutcomeStatus.PENDING, review_id=self.report_id)
            return RequestOutcome(
                status=ReviewRequestOutcomeStatus.COMPLETED, review_id=self.report_id, run_index=run_index
            )
        ended = [marker for marker in review_markers if marker.review_mode == requested_mode]
        if not ended:
            return None
        return self._ended_outcome(ended[-1], state)

    def _resolve_outcome(
        self, requested_at: datetime, resolution: ResolutionSummary | None, state: ReviewPRState
    ) -> RequestOutcome | None:
        if self.report_id is None:
            return None
        if resolution is not None and _resolution_answers(resolution, requested_at):
            if resolution.status == RESOLUTION_COMPLETED:
                return RequestOutcome(status=ReviewRequestOutcomeStatus.COMPLETED, review_id=self.report_id)
            if resolution.status == RESOLUTION_STOPPED:
                # A run can go quiet in the database while its workflow still works through threads.
                if state in _RUNNING_STATES:
                    return RequestOutcome(status=ReviewRequestOutcomeStatus.PENDING, review_id=self.report_id)
                if state == ReviewPRState.UNKNOWN:
                    return RequestOutcome(status=ReviewRequestOutcomeStatus.UNKNOWN, review_id=self.report_id)
                return RequestOutcome(
                    status=ReviewRequestOutcomeStatus.FAILED, reason=STOPPED_REASON, review_id=self.report_id
                )
            return RequestOutcome(status=ReviewRequestOutcomeStatus.PENDING, review_id=self.report_id)
        skipped = [
            marker
            for marker in run_outcome_markers(self.team_id, [self.report_id], since=requested_at)[self.report_id]
            if marker.stage == RUN_STAGE_RESOLUTION
        ]
        if not skipped:
            return None
        return self._ended_outcome(skipped[-1], state)

    def _unmatched_outcome(self, state: ReviewPRState) -> RequestOutcome:
        """No run answered the request yet: wait while anything runs, else the queue dropped or replaced it."""
        if state in _RUNNING_STATES:
            return RequestOutcome(status=ReviewRequestOutcomeStatus.PENDING, review_id=self.report_id)
        if state == ReviewPRState.UNKNOWN:
            return RequestOutcome(status=ReviewRequestOutcomeStatus.UNKNOWN, review_id=self.report_id)
        return RequestOutcome(
            status=ReviewRequestOutcomeStatus.FAILED, reason=NO_MATCHING_RUN_REASON, review_id=self.report_id
        )

    def status(self, requested_at: datetime | None, run_mode: str) -> PRStatus:
        state = self._state()
        resolution = (
            latest_resolution_summaries(self.team_id, [self.report]).get(self.report_id)
            if self.report is not None and self.report_id is not None
            else None
        )
        request_outcome: RequestOutcome | None = None
        if requested_at is not None:
            if run_mode == RUN_MODE_RESOLVE_ONLY:
                request_outcome = self._resolve_outcome(requested_at, resolution, state)
            else:
                requested_mode = REVIEW_MODE_FLASH if run_mode == RUN_MODE_FLASH else REVIEW_MODE_FULL
                request_outcome = self._review_outcome(requested_at, requested_mode, state)
            if request_outcome is None:
                request_outcome = self._unmatched_outcome(state)
        return PRStatus(
            repository=self.report.repository if self.report is not None else self.repository,
            pr_number=self.pr_number,
            report_id=self.report_id,
            state=state,
            latest_review=self._latest_review(),
            latest_resolution=resolution,
            request_outcome=request_outcome,
        )
