"""Queue one automatic Deep review after an automatic Standard review that found a must-fix issue."""

from typing import TYPE_CHECKING

from products.review_hog.backend.automatic_reviews import deep_turn_known
from products.review_hog.backend.models import ReviewReport, ReviewRepository
from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FULL, effective_priority
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_valid_findings

if TYPE_CHECKING:
    from products.review_hog.backend.temporal.types import FinishedStandardAutomaticTurn


class DeepFollowUp:
    def __init__(self, turn: "FinishedStandardAutomaticTurn") -> None:
        self.turn = turn

    def start(self) -> None:
        turn = self.turn
        # A payload from before the fields has no user to run the Deep review as.
        if turn.draft or turn.user_id is None:
            return
        row = (
            ReviewRepository.objects.for_team(turn.team_id)
            .filter(full_name__iexact=turn.repository, deep_review_gated_prs=True)
            .first()
        )
        if row is None or not self._found_must_fix():
            return
        report = ReviewReport.objects.for_team(turn.team_id).filter(id=turn.report_id).first()
        # None means the queue did not answer, and every doubt leaves the PR with its Standard review.
        if deep_turn_known(turn.team_id, turn.repository, turn.pr_number, report) is not False:
            return
        # The temporal package imports the activities, which call this class.
        from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
        from products.review_hog.backend.temporal.types import DEEP_FOLLOW_UP_ACTION, TRIGGER_AUTOMATIC  # noqa: PLC0415

        start_review_pr_workflow(
            pr_url=f"https://github.com/{turn.repository}/pull/{turn.pr_number}",
            team_id=turn.team_id,
            user_id=turn.user_id,
            acting_user_id=turn.user_id,
            publish=True,
            # A Deep review chains into resolution unless this is False, and an automatic review never writes code.
            resolve_comments=False,
            review_mode=REVIEW_MODE_FULL,
            trigger_source=TRIGGER_AUTOMATIC,
            trigger_action=DEEP_FOLLOW_UP_ACTION,
            requested_head_sha=turn.head_sha,
            installation_id=row.installation_id,
            github_repo_id=row.github_repo_id,
        )

    def _found_must_fix(self) -> bool:
        return any(
            effective_priority(finding.priority, verdict.adjusted_priority) == IssuePriority.MUST_FIX
            for finding, verdict in load_valid_findings(
                team_id=self.turn.team_id, report_id=self.turn.report_id, run_index=self.turn.run_index
            )
        )
