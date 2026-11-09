"""Starts a silent stamphog review when a Standard review of a PR that opened or was marked ready ends clean.

Stamphog posts only an approval from that review and keeps every other verdict off the PR, so the
author of a clean PR can get an approval without adding the stamphog label. ReviewHog decides only
whether its own turn was clean and complete. Stamphog checks its repository switch, the PR and the
head again when its task runs.
"""

from posthog.dataclasses import frozen

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH
from products.review_hog.backend.reviewer.persistence import load_pr_snapshot, load_valid_findings
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_SINGLE_AGENT
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import plan_lens_chunks
from products.review_hog.backend.turn_coverage import turn_markers, turn_unread_paths
from products.stamphog.backend.facade.tasks import queue_silent_review

# A push to an open PR is a follow-up, and stamphog's label and review-mode paths already cover it.
SILENT_STAMPHOG_ACTIONS = frozenset({"opened", "ready_for_review"})


def _single_agent(marker: TurnMarkerArtefact) -> bool:
    return marker.fingerprint_inputs.get("review_design") == REVIEW_DESIGN_SINGLE_AGENT


def _lens_chunks_capped(report: ReviewReport, *, head_sha: str, single_agent: bool) -> bool:
    """Whether a single-agent turn on the head reviewed past the lens part cap, as the fetch decided it.

    The plan is not stored, so it is computed again from the turn's PR snapshot. Without a snapshot
    the answer is unknown, and the turn counts as capped.
    """
    if not single_agent:
        return False
    snapshot = load_pr_snapshot(
        team_id=report.team_id, report_id=str(report.id), head_sha=head_sha, review_design=REVIEW_DESIGN_SINGLE_AGENT
    )
    if snapshot is None:
        return True
    return plan_lens_chunks(snapshot.pr_files).capped


@frozen
class FinishedTurn:
    """A review turn that completed without an error, as the workflow saw it."""

    team_id: int
    report_id: str
    repository: str
    pr_number: int
    run_index: int
    review_mode: str
    head_sha: str
    # The head the triggering event named. The turn reviews the live head, which can be newer.
    requested_head_sha: str | None
    trigger_action: str | None
    draft: bool
    lens_chunks_capped: bool

    @classmethod
    def completed_automatic_turn(
        cls, report: ReviewReport, *, pr_number: int, head_sha: str, trigger_action: str, draft: bool
    ) -> "FinishedTurn | None":
        """The finished turn that gave `head_sha` its automatic review, seen with a later event for the same head.

        The workflow skips an automatic request for a head that already has its automatic review, so
        a draft marked ready without a push gets no new turn. The earlier turn then stands in for it.
        """
        if report.automatic_reviewed_head_sha != head_sha:
            return None
        markers = turn_markers(team_id=report.team_id, report_id=str(report.id), head_sha=head_sha)
        # run_count counts finished turns, so a higher run index belongs to a turn that failed or still runs.
        finished = [marker for marker in markers.values() if marker.run_index <= report.run_count and marker.publishes]
        if not finished:
            return None
        marker = max(finished, key=lambda candidate: candidate.run_index)
        return cls(
            team_id=report.team_id,
            report_id=str(report.id),
            repository=report.repository,
            pr_number=pr_number,
            run_index=marker.run_index,
            review_mode=marker.review_mode,
            head_sha=head_sha,
            requested_head_sha=head_sha,
            trigger_action=trigger_action,
            draft=draft,
            lens_chunks_capped=_lens_chunks_capped(report, head_sha=head_sha, single_agent=_single_agent(marker)),
        )

    def is_clean_full_coverage(self) -> bool:
        if self.review_mode != REVIEW_MODE_FLASH:
            return False
        if self.trigger_action not in SILENT_STAMPHOG_ACTIONS:
            return False
        if self.head_sha != self.requested_head_sha:
            return False
        if self.draft or self.lens_chunks_capped:
            return False
        # Every valid finding counts, also one below the urgency threshold that the turn did not post.
        if load_valid_findings(team_id=self.team_id, report_id=self.report_id, run_index=self.run_index):
            return False
        unread = turn_unread_paths(
            team_id=self.team_id, report_id=self.report_id, head_sha=self.head_sha, run_index=self.run_index
        )
        return unread == ()

    def start_silent_stamphog(self) -> bool:
        """Queue the silent stamphog review when the turn qualifies. Returns whether it was queued."""
        if not self.is_clean_full_coverage():
            return False
        queue_silent_review(
            team_id=self.team_id, repository=self.repository, pr_number=self.pr_number, head_sha=self.head_sha
        )
        return True
