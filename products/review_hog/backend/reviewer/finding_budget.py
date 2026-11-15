"""The finding budget: how many findings automatic Standard reviews post on one pull request in total.

Each Standard turn already keeps only a few findings (`compose_flash_findings`). On a busy pull request
those add up turn after turn, and the late ones are rarely acted on. The budget counts every finding
ever posted on the pull request, by any review mode and trigger. Once the count reaches `FINDING_BUDGET`,
an automatic turn posts only its must-fix findings, and the others drop with the `budget` disposition.
Automatic reviews run on every pull request as a safeguard, so past the budget they only raise what must
be fixed. A review someone asks for (a comment, the label, the UI) is not limited.

The count never goes down. Fixing or resolving a finding gives no budget back, because a coding agent
that fixes and resolves everything would otherwise refill it forever. A dropped finding is not queued
for a later turn, and the next turn that finds it again drops it again.

Pull requests split into two arms by a hash of the repository and number, so the effect can be measured
against pull requests that keep posting. The cap comes from a replay of 30 days of closed pull requests
in `review-eval/experiments/2026-10-14-review-throttle`.
"""

import hashlib
from collections.abc import Sequence
from typing import Literal

from posthog.dataclasses import frozen
from posthog.utils import pluralize

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.constants import effective_priority, published_priorities_for
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority

FINDING_BUDGET = 20
ROUND_CAP = 3

BudgetArm = Literal["budget", "control"]


def budget_arm(repository: str, pr_number: int | None) -> BudgetArm:
    """The arm of a pull request, stable for its whole life. A run without a pull request posts nothing."""
    if pr_number is None:
        return "control"
    digest = hashlib.sha256(f"{repository.lower()}#{pr_number}".encode()).digest()
    return "budget" if digest[0] % 2 == 0 else "control"


def budget_note(dropped: int, comment_commands_on: bool) -> str:
    """The line a review ends with when the budget kept some of its findings off the pull request.

    It offers a Deep review, because this head already has its Standard review and a second one would not run.
    """
    note = (
        f"This pull request reached its limit of {FINDING_BUDGET} automatic review findings, so this review left "
        f"out {pluralize(dropped, 'lower-priority finding')}. Must-fix findings still post."
    )
    if comment_commands_on:
        note = f"{note} Comment `@posthog review --deep` for a review without the limit."
    return note


@frozen
class FindingBudget:
    arm: BudgetArm
    # Findings the pull request showed before this turn.
    posted_before: int

    @classmethod
    def for_turn(
        cls, report: ReviewReport, prior_findings: Sequence[tuple[ReviewIssueFinding, ValidationVerdict | None]]
    ) -> "FindingBudget":
        """`prior_findings` are the findings of the turns before this one, with their verdicts."""
        return cls(
            arm=budget_arm(report.repository, report.pr_number), posted_before=_posted_count(report, prior_findings)
        )

    @property
    def left(self) -> int | None:
        """How many more findings the pull request may post, None for a pull request outside the budget."""
        if self.arm == "control":
            return None
        return max(FINDING_BUDGET - self.posted_before, 0)


@frozen
class ReviewRound:
    """Which review round a turn is on its pull request: the turns that published before it, plus one.

    A round is a turn that posted to GitHub, by any mode and trigger, the same count the finding budget
    uses. A turn that kept nothing is not a round, so a clean turn repeats the number of the next one.
    """

    number: int

    @classmethod
    def for_turn(cls, report: ReviewReport, *, run_index: int) -> "ReviewRound":
        published_before = sum(1 for index in (report.published_head_shas or {}) if int(index) < run_index)
        return cls(number=published_before + 1)

    @property
    def asks_for_a_rethink(self) -> bool:
        return self.number >= ROUND_CAP


def round_note(review_round: ReviewRound) -> str:
    """The line a review ends with from round `ROUND_CAP` on, so the author reconsiders the approach.

    An author and a reviewer that fix and re-review one finding at a time can loop for a long time, and most
    of what a late round flags was already there in the first one.
    """
    return (
        f"This is review round {review_round.number} on this pull request. When findings keep coming back in the "
        "same code, the approach is usually the problem. Before the next fix, check whether a different design "
        "would remove the whole class of findings."
    )


def _posted_count(report: ReviewReport, findings: Sequence[tuple[ReviewIssueFinding, ValidationVerdict | None]]) -> int:
    """The valid findings that published turns let through their urgency threshold.

    Only turns with a stored threshold count. Turns published before the threshold was stored are older
    than the budget and stay out of it.
    """
    thresholds = report.published_urgency_thresholds or {}
    count = 0
    for finding, verdict in findings:
        threshold = thresholds.get(str(finding.run_index))
        if verdict is None or not verdict.is_valid or threshold is None:
            continue
        if effective_priority(finding.priority, verdict.adjusted_priority) in published_priorities_for(
            IssuePriority(threshold)
        ):
            count += 1
    return count
