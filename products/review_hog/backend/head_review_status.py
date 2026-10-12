"""Where PostHog Review's review of one PR head stands. Read through `facade/review_status.py`.

The answer is per head, unlike `pr_status.PRStatusLookup`, which reports "queued" for the whole PR.
The database answers for turns that started: a running turn keeps the report ACTIVE on its head
until its findings are on the PR, and a finished turn leaves a turn marker, the completed head, and
the published heads. A request that waits in the PR's review queue exists only in the queue
workflow, so the workflow's `requested_heads` query answers for it.
"""

from datetime import timedelta

from products.review_hog.backend.facade.review_status_types import HeadReviewState, HeadReviewStatus
from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.persistence import load_turn_findings
from products.review_hog.backend.reviewer.progress import (
    RUN_OUTCOME_FAILED,
    RUN_STAGE_REVIEW,
    finding_counts,
    in_progress_report_ids,
    run_outcome_markers,
    turn_markers,
)
from products.review_hog.backend.reviewer.review_state import turn_review_mode
from products.review_hog.backend.temporal.client import queued_review_heads
from products.review_hog.backend.temporal.types import review_pr_workflow_id

_KIND_NAMES = {REVIEW_MODE_FLASH: "Standard", REVIEW_MODE_FULL: "Deep"}
# Callers poll, for example stamphog every 30 seconds, so a slow queue answer must not hold them.
_QUERY_RPC_TIMEOUT = timedelta(seconds=2)


class HeadReviewStatusLookup:
    def __init__(self, team_id: int, repository: str, pr_number: int, head_sha: str) -> None:
        self.team_id = team_id
        self.repository = repository
        self.pr_number = pr_number
        self.head_sha = head_sha
        # Repository casing can differ per trigger, so match it the way the trigger does.
        self.report = (
            ReviewReport.objects.for_team(team_id).filter(repository__iexact=repository, pr_number=pr_number).first()
        )
        self.report_id = str(self.report.id) if self.report is not None else ""

    def _status(
        self, state: HeadReviewState, *, review_kind: str = "", findings_count: int = 0, published: bool = False
    ) -> HeadReviewStatus:
        return HeadReviewStatus(
            state=state,
            review_kind=review_kind,
            findings_count=findings_count,
            published=published,
            head_sha=self.head_sha,
        )

    def _running_head(self) -> str | None:
        """The head of the turn that runs now, or None. A turn stays ACTIVE through its publish."""
        report = self.report
        if report is None or report.status != ReviewReport.Status.ACTIVE:
            return None
        if self.report_id not in in_progress_report_ids(self.team_id, [report]):
            return None
        return report.head_sha

    def _queued(self, running_head: str | None) -> bool:
        owner, _, repo = self.repository.partition("/")
        workflow_id = review_pr_workflow_id(team_id=self.team_id, owner=owner, repo=repo, pr_number=self.pr_number)
        heads = queued_review_heads(workflow_id, rpc_timeout=_QUERY_RPC_TIMEOUT)
        if self.head_sha in heads:
            return True
        # A request without a head reviews the live head when its turn starts. While a turn runs on
        # another head, that request is most likely the running turn itself.
        return None in heads and running_head is None

    def _finished(self) -> HeadReviewStatus | None:
        report = self.report
        if report is None:
            return None
        markers = turn_markers(self.team_id, [self.report_id])
        completed_runs = [
            run_index
            for (_, run_index), marker in markers.items()
            if marker.head_sha == self.head_sha and run_index <= report.run_count
        ]
        # Turns that started before turn markers existed have none, so the latest turn's head counts too.
        if report.run_count and report.completed_head_sha == self.head_sha:
            completed_runs.append(report.run_count)
        failed_runs = {
            marker.run_index
            for marker in run_outcome_markers(self.team_id, [self.report_id])[self.report_id]
            if marker.stage == RUN_STAGE_REVIEW
            and marker.outcome == RUN_OUTCOME_FAILED
            and marker.head_sha == self.head_sha
        }
        if not completed_runs:
            return self._status(HeadReviewState.FAILED) if failed_runs else None
        run_index = max(completed_runs)
        # Finalize counts a turn before it publishes, so a failed publish marks a counted turn failed.
        if run_index in failed_runs:
            return self._status(HeadReviewState.FAILED)
        pairs = load_turn_findings(team_id=self.team_id, report_id=self.report_id, run_index=run_index)
        counts, _ = finding_counts(pairs)
        marker = markers.get((self.report_id, run_index))
        review_mode = marker.review_mode if marker is not None else turn_review_mode(pairs)
        return self._status(
            HeadReviewState.COMPLETED,
            review_kind=_KIND_NAMES.get(review_mode, ""),
            findings_count=sum(counts.values()),
            published=(report.published_head_shas or {}).get(str(run_index)) == self.head_sha,
        )

    def status(self) -> HeadReviewStatus | None:
        running_head = self._running_head()
        if running_head == self.head_sha or self._queued(running_head):
            return self._status(HeadReviewState.PENDING)
        return self._finished()
