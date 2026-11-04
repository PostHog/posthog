"""Where PostHog Review's review of one PR head stands. Read through `facade/review_status.py`.

The answer is per head, unlike `pr_status.PRStatusLookup`, which reports "queued" for the whole PR.
The database answers for turns that started: a running turn keeps the report ACTIVE on its head
until its findings are on the PR, and a finished turn leaves a turn marker, the completed head, and
the published heads. A request that waits in the PR's review queue exists only in the queue
workflow, so the workflow's `requested_heads` query answers for it.
"""

from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from products.review_hog.backend.facade.review_status_types import HeadReviewState, HeadReviewStatus
from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.reviewer.persistence import (
    load_chunk_set,
    load_turn_findings,
    reviewed_pipeline_chunk_ids,
)
from products.review_hog.backend.reviewer.progress import (
    RUN_OUTCOME_FAILED,
    RUN_STAGE_REVIEW,
    finding_counts,
    in_progress_report_ids,
    run_outcome_markers,
)
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.review_state import turn_review_mode
from products.review_hog.backend.temporal.client import queued_review_heads
from products.review_hog.backend.temporal.types import review_pr_workflow_id

_KIND_NAMES = {REVIEW_MODE_FLASH: "Standard", REVIEW_MODE_FULL: "Deep"}
# Callers poll, for example stamphog every 30 seconds, so a slow queue answer must not hold them.
_QUERY_RPC_TIMEOUT = timedelta(seconds=2)


@frozen
class _Turn:
    marker: TurnMarkerArtefact
    # When the newest marker row of the turn was written, which is when its last attempt started.
    started_at: datetime


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
        self,
        state: HeadReviewState,
        *,
        review_kind: str = "",
        findings_count: int = 0,
        published: bool = False,
        base_branch: str = "",
        base_sha: str = "",
        skipped_paths: tuple[str, ...] = (),
    ) -> HeadReviewStatus:
        return HeadReviewStatus(
            state=state,
            review_kind=review_kind,
            findings_count=findings_count,
            published=published,
            head_sha=self.head_sha,
            base_branch=base_branch,
            base_sha=base_sha,
            skipped_paths=skipped_paths,
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
        if self.head_sha in heads.active or self.head_sha in heads.pending:
            return True
        # A request without a head reviews the live head when its turn starts. A waiting one has not
        # started yet. The active one is the running turn when a turn runs on another head.
        return None in heads.pending or (None in heads.active and running_head is None)

    def _turns_on_head(self) -> dict[int, _Turn]:
        """Each turn on this head by run index, from its marker. The newest row of a retried turn wins."""
        rows = (
            ReviewReportArtefact.objects.for_team(self.team_id)
            .filter(
                report_id=self.report_id,
                type=ReviewReportArtefact.ArtefactType.TURN_MARKER,
                head_sha=self.head_sha,
            )
            .order_by("created_at", "id")
            .values("content", "created_at")
        )
        turns: dict[int, _Turn] = {}
        for row in rows:
            marker = TurnMarkerArtefact.model_validate_json(row["content"])
            turns[marker.run_index] = _Turn(marker=marker, started_at=row["created_at"])
        return turns

    def _skipped_paths(self, turn: _Turn | None) -> tuple[str, ...]:
        """The files the turn left out, plus the files of every pipeline chunk that no review unit finished.

        The fan-out fails a turn only when most of its units fail, so a turn can complete with a chunk unread.
        """
        if turn is None:
            return ()
        skipped = list(turn.marker.skipped_paths or ())
        # A single-agent turn fails when its main session fails, and that session reviews the whole diff.
        if turn.marker.fingerprint_inputs.get("review_design") == REVIEW_DESIGN_SINGLE_AGENT:
            return tuple(skipped)
        chunks = load_chunk_set(team_id=self.team_id, report_id=self.report_id, head_sha=self.head_sha)
        # Without the chunking the gaps are unknown, so the turn keeps only the files it left out.
        if chunks is None:
            return tuple(skipped)
        reviewed = reviewed_pipeline_chunk_ids(team_id=self.team_id, report_id=self.report_id, head_sha=self.head_sha)
        for chunk in chunks.chunks:
            if chunk.chunk_id in reviewed:
                continue
            for file in chunk.files:
                if file.filename not in skipped:
                    skipped.append(file.filename)
        return tuple(skipped)

    def _finished(self) -> HeadReviewStatus | None:
        report = self.report
        if report is None:
            return None
        published_heads = report.published_head_shas or {}

        def posted(run_index: int) -> bool:
            return published_heads.get(str(run_index)) == self.head_sha

        turns = {run_index: turn for run_index, turn in self._turns_on_head().items() if run_index <= report.run_count}
        # Only a turn that posts to the PR is a review of the PR. An eval or CLI turn is not, even
        # with valid findings. A clean publishing turn posts nothing and still counts. A marker
        # from before `publishes` existed counts only when its turn posted.
        completed_runs = [
            run_index
            for run_index, turn in turns.items()
            if turn.marker.publishes or (turn.marker.publishes is None and posted(run_index))
        ]
        # Turns that started before turn markers existed have none, so the latest turn's head counts too.
        if (
            report.run_count
            and report.completed_head_sha == self.head_sha
            and report.run_count not in turns
            and posted(report.run_count)
        ):
            completed_runs.append(report.run_count)
        failed_at: dict[int | None, datetime] = {
            marker.run_index: marker.created_at
            for marker in run_outcome_markers(self.team_id, [self.report_id])[self.report_id]
            if marker.stage == RUN_STAGE_REVIEW
            and marker.outcome == RUN_OUTCOME_FAILED
            and marker.head_sha == self.head_sha
        }
        if not completed_runs:
            return self._status(HeadReviewState.FAILED) if failed_at else None
        run_index = max(completed_runs)
        turn = turns.get(run_index)
        # Finalize counts a turn before it publishes, so a failed publish marks a counted turn failed.
        # A failure from before the turn's last attempt started belongs to an attempt that a
        # successful retry replaced.
        if run_index in failed_at and (turn is None or failed_at[run_index] > turn.started_at):
            return self._status(HeadReviewState.FAILED)
        pairs = load_turn_findings(team_id=self.team_id, report_id=self.report_id, run_index=run_index)
        counts, _ = finding_counts(pairs)
        review_mode = turn.marker.review_mode if turn is not None else turn_review_mode(pairs)
        return self._status(
            HeadReviewState.COMPLETED,
            review_kind=_KIND_NAMES.get(review_mode, ""),
            findings_count=sum(counts.values()),
            published=posted(run_index),
            base_branch=(turn.marker.base_branch or "") if turn is not None else "",
            base_sha=(turn.marker.base_sha or "") if turn is not None else "",
            skipped_paths=self._skipped_paths(turn),
        )

    def status(self) -> HeadReviewStatus | None:
        running_head = self._running_head()
        if running_head == self.head_sha or self._queued(running_head):
            return self._status(HeadReviewState.PENDING)
        return self._finished()
