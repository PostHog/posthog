"""Starts a silent stamphog review when a Standard review of a PR that opened or was marked ready ends clean.

Stamphog posts only an approval from that review and keeps every other verdict off the PR, so the
author of a clean PR can get an approval without adding the stamphog label. ReviewHog decides only
whether its own turn was clean and complete. Stamphog checks its repository switch, the PR and the
head again when its task runs.
"""

from posthog.dataclasses import frozen

from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH
from products.review_hog.backend.reviewer.persistence import load_valid_findings
from products.review_hog.backend.turn_coverage import turn_unread_paths
from products.stamphog.backend.facade.tasks import queue_silent_review

# A push to an open PR is a follow-up, and stamphog's label and review-mode paths already cover it.
SILENT_STAMPHOG_ACTIONS = frozenset({"opened", "ready_for_review"})


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
