"""A pull request's delivery timeline: what it waited on at every moment from ready to merge.

The warehouse holds immutable timestamps (run attempts, job attempts, reviews, merge-queue gate
runs), not a state history, so the timeline is replayed from them. Every timestamp becomes a
change point, the state is evaluated once per interval between two points, and equal neighbours
merge into one segment. The evaluation is a fixed precedence, most blocking first:

1. Merge queue: inside a gate attempt, or from the first gate attempt after the last push to the
   merge. Every queue state (own test, a collateral restart, an ejection, a cancel gap) collapses
   into this one span, because the warehouse keeps no queue transition history.
2. Out of the merge queue: an open PR whose last gate attempt ended and whose current Trunk state
   is failed or cancelled. Current state only, so this never appears on a merged PR.
3. Red CI on the head commit, labelled by what turned it green (see ``_red_kind``).
4. CI running on the head commit.
5. Review state from each reviewer's latest verdict: changes requested with no push since while any
   reviewer's latest verdict requests changes, approved when none does, else waiting for review.

A commit's check state per workflow is its latest attempt: a re-run in flight reads as running,
not red, the same way GitHub shows it. A run that exists but has not started yet also reads as
running, because the wait for a runner is CI time, not review time.
"""

import bisect
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    PRTimelinePush,
    PRTimelineSegment,
    PRTimelineSegmentKind,
)
from products.engineering_analytics.backend.logic.merge_queue import GateAttempt
from products.engineering_analytics.backend.logic.queries.master_failures import strip_shard_suffix
from products.engineering_analytics.backend.logic.views.reviews import APPROVED_STATE, CHANGES_REQUESTED_STATE

# A PR job failure counts as "master broken" when the same job failed on the default branch this
# close to it. Wide enough for a master fix to take a few hours, narrow enough that an unrelated
# failure of the same job days apart does not explain it.
MASTER_FAILURE_PROXIMITY = timedelta(hours=12)


@frozen
class RunAttempt:
    """One attempt of one workflow run on a PR commit, with merge-queue gate runs excluded."""

    run_id: int
    workflow_name: str
    head_sha: str
    attempt: int
    # When the workflow run was created. A queued run starts later.
    queued_at: datetime
    started_at: datetime
    # None while the attempt is still running.
    completed_at: datetime | None
    failed: bool
    # Cancelled, neutral and action-required attempts are neither failed nor succeeded.
    succeeded: bool
    # Names of the jobs that failed in this attempt; empty when job data is not synced.
    failed_jobs: tuple[str, ...]


@frozen
class Push:
    head_sha: str
    pushed_at: datetime


@frozen
class ReviewVerdict:
    reviewer: str
    state: str
    submitted_at: datetime


class MasterFailureIndex:
    """Default-branch job failures, looked up by workflow and de-sharded job name."""

    def __init__(self, failures: list[tuple[str, str, datetime]]) -> None:
        self._completed: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        for workflow_name, job_name, completed_at in failures:
            self._completed[(workflow_name, strip_shard_suffix(job_name))].append(completed_at)
        for times in self._completed.values():
            times.sort()

    def explains(self, attempt: RunAttempt) -> bool:
        """True when every failed job of the attempt also failed on the default branch close to it.
        An attempt without job names (no job data) is never explained."""
        if not attempt.failed_jobs or attempt.completed_at is None:
            return False
        return all(self._failed_near(attempt.workflow_name, job, attempt.completed_at) for job in attempt.failed_jobs)

    def _failed_near(self, workflow_name: str, job_name: str, at: datetime) -> bool:
        times = self._completed.get((workflow_name, strip_shard_suffix(job_name)), [])
        index = bisect.bisect_left(times, at - MASTER_FAILURE_PROXIMITY)
        return index < len(times) and times[index] <= at + MASTER_FAILURE_PROXIMITY


@dataclass(frozen=True, kw_only=True)
class PRTimelineInput:
    started_at: datetime
    # The merge, the close, or now for an open PR.
    ended_at: datetime
    is_open: bool
    is_merged: bool
    is_draft: bool
    pushes: list[Push]
    attempts: list[RunAttempt]
    gate_attempts: list[GateAttempt]
    # None when the reviews table is not synced.
    reviews: list[ReviewVerdict] | None
    # Current Trunk state is failed or cancelled. Only meaningful for an open PR.
    trunk_out_of_queue: bool


@frozen
class _QueueSpan:
    started_at: datetime | None
    ended_at: datetime | None


@frozen
class _Push:
    head_sha: str
    pushed_at: datetime
    # Attempts per workflow, oldest first.
    attempts_by_workflow: dict[str, list[RunAttempt]]


class PRTimelineBuilder:
    def __init__(self, pr: PRTimelineInput, master_failures: MasterFailureIndex) -> None:
        self._pr = pr
        self._master_failures = master_failures
        self._pushes = self._group_pushes(pr.pushes, pr.attempts)
        self._push_times = [push.pushed_at for push in self._pushes]
        self._verdicts = sorted(
            (review for review in pr.reviews or [] if review.state in (APPROVED_STATE, CHANGES_REQUESTED_STATE)),
            key=lambda review: review.submitted_at,
        )
        queue_span = self._queue_span()
        self._queue_from, self._queue_until = queue_span.started_at, queue_span.ended_at

    @staticmethod
    def _group_pushes(pushes: list[Push], attempts: list[RunAttempt]) -> list[_Push]:
        by_sha: dict[str, list[RunAttempt]] = defaultdict(list)
        for attempt in attempts:
            by_sha[attempt.head_sha].append(attempt)
        grouped = []
        for push in pushes:
            sha_attempts = by_sha[push.head_sha]
            by_workflow: dict[str, list[RunAttempt]] = defaultdict(list)
            for attempt in sorted(sha_attempts, key=lambda a: (a.started_at, a.attempt)):
                by_workflow[attempt.workflow_name].append(attempt)
            grouped.append(
                _Push(head_sha=push.head_sha, pushed_at=push.pushed_at, attempts_by_workflow=dict(by_workflow))
            )
        return sorted(grouped, key=lambda push: push.pushed_at)

    def _queue_span(self) -> _QueueSpan:
        """The continuous queue stretch: from the first gate attempt after the last push to the merge
        (merged PR), or to the end of the last gate attempt (open or closed PR; the end while one still runs)."""
        last_push_at = self._push_times[-1] if self._push_times else None
        after_last_push = [
            gate for gate in self._pr.gate_attempts if last_push_at is None or gate.started_at >= last_push_at
        ]
        if not after_last_push:
            return _QueueSpan(started_at=None, ended_at=None)
        queue_from = min(gate.started_at for gate in after_last_push)
        if self._pr.is_merged or any(gate.completed_at is None for gate in after_last_push):
            return _QueueSpan(started_at=queue_from, ended_at=self._pr.ended_at)
        return _QueueSpan(
            started_at=queue_from,
            ended_at=max(gate.completed_at for gate in after_last_push if gate.completed_at is not None),
        )

    def pushes(self) -> list[PRTimelinePush]:
        return [PRTimelinePush(head_sha=push.head_sha, pushed_at=push.pushed_at) for push in self._pushes]

    def build(self) -> list[PRTimelineSegment]:
        start, end = self._pr.started_at, self._pr.ended_at
        if end <= start:
            return []
        if self._pr.is_draft:
            return [PRTimelineSegment(kind=PRTimelineSegmentKind.DRAFT, started_at=start, ended_at=end)]

        points = sorted({start, end, *(point for point in self._change_points() if start < point < end)})
        segments: list[PRTimelineSegment] = []
        for left, right in pairwise(points):
            kind = self._kind_at(left)
            if segments and segments[-1].kind == kind:
                segments[-1] = PRTimelineSegment(kind=kind, started_at=segments[-1].started_at, ended_at=right)
            else:
                segments.append(PRTimelineSegment(kind=kind, started_at=left, ended_at=right))
        return segments

    def _change_points(self) -> list[datetime]:
        points: list[datetime] = [*self._push_times]
        for attempt in self._pr.attempts:
            points.append(attempt.queued_at)
            points.append(attempt.started_at)
            if attempt.completed_at is not None:
                points.append(attempt.completed_at)
        for gate in self._pr.gate_attempts:
            points.append(gate.started_at)
            if gate.completed_at is not None:
                points.append(gate.completed_at)
        points.extend(review.submitted_at for review in self._verdicts)
        points.extend(point for point in (self._queue_from, self._queue_until) if point is not None)
        return points

    def _kind_at(self, at: datetime) -> PRTimelineSegmentKind:
        if self._in_queue(at):
            return PRTimelineSegmentKind.MERGE_QUEUE
        if self._pr.is_open and self._pr.trunk_out_of_queue and self._queue_until and at >= self._queue_until:
            return PRTimelineSegmentKind.OUT_OF_MERGE_QUEUE
        push = self._head_at(at)
        if push is not None:
            failed, running = self._check_state(push, at)
            if failed:
                return self._red_kind(push, failed, at)
            if running:
                return PRTimelineSegmentKind.CI_RUNNING
        return self._review_kind(push, at)

    def _in_queue(self, at: datetime) -> bool:
        if (
            self._queue_from is not None
            and self._queue_until is not None
            and self._queue_from <= at < self._queue_until
        ):
            return True
        return any(
            gate.started_at <= at and (gate.completed_at is None or at < gate.completed_at)
            for gate in self._pr.gate_attempts
        )

    def _head_at(self, at: datetime) -> _Push | None:
        index = bisect.bisect_right(self._push_times, at)
        return self._pushes[index - 1] if index else None

    @staticmethod
    def _check_state(push: _Push, at: datetime) -> tuple[list[RunAttempt], bool]:
        """The head commit's failed latest attempts and whether any latest attempt still runs or waits to start."""
        failed: list[RunAttempt] = []
        running = False
        for attempts in push.attempts_by_workflow.values():
            started = [attempt for attempt in attempts if attempt.started_at <= at]
            if not started:
                # Only a first attempt proves a queue wait. A re-run starts after the push's first CI.
                if any(attempt.attempt == 1 and attempt.queued_at <= at for attempt in attempts):
                    running = True
                continue
            latest = started[-1]
            if latest.completed_at is None or latest.completed_at > at:
                running = True
            elif latest.failed:
                failed.append(latest)
        return failed, running

    def _red_kind(self, push: _Push, failed: list[RunAttempt], at: datetime) -> PRTimelineSegmentKind:
        """What turned the red checks green, in order of how much it clears the author:

        - passed on a re-run: every failed workflow passed a later attempt on the same commit;
        - master broken: every failed job failed on the default branch close to the failure;
        - fixed by a push: a later commit arrived before the end;
        - not provable: none of those, including a check that is still red now.

        A mix of causes across workflows falls through to the weaker label on purpose.
        """
        if all(self._passed_later(push, attempt) for attempt in failed):
            return PRTimelineSegmentKind.RED_PASSED_ON_RERUN
        if all(self._master_failures.explains(attempt) for attempt in failed):
            return PRTimelineSegmentKind.RED_MASTER_BROKEN
        if bisect.bisect_right(self._push_times, at) < len(self._pushes):
            return PRTimelineSegmentKind.RED_FIXED_BY_PUSH
        return PRTimelineSegmentKind.RED_NOT_PROVABLE

    @staticmethod
    def _passed_later(push: _Push, failed: RunAttempt) -> bool:
        assert failed.completed_at is not None
        return any(
            attempt.started_at >= failed.completed_at and attempt.completed_at is not None and attempt.succeeded
            for attempt in push.attempts_by_workflow[failed.workflow_name]
        )

    def _review_kind(self, push: _Push | None, at: datetime) -> PRTimelineSegmentKind:
        if self._pr.reviews is None:
            return PRTimelineSegmentKind.REVIEW_STATE_UNKNOWN
        # GitHub keeps a change request open until the same reviewer approves, so another reviewer's
        # approval does not clear it. Only each reviewer's latest verdict counts.
        latest_by_reviewer: dict[str, ReviewVerdict] = {}
        for review in self._verdicts:
            if review.submitted_at > at:
                break
            latest_by_reviewer[review.reviewer] = review
        if not latest_by_reviewer:
            return PRTimelineSegmentKind.WAITING_FOR_REVIEW
        change_requests = [review for review in latest_by_reviewer.values() if review.state == CHANGES_REQUESTED_STATE]
        if not change_requests:
            return PRTimelineSegmentKind.APPROVED_NOT_ENQUEUED
        if push is not None and push.pushed_at > max(review.submitted_at for review in change_requests):
            return PRTimelineSegmentKind.WAITING_FOR_REVIEW
        return PRTimelineSegmentKind.CHANGES_REQUESTED
