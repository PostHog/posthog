import pytest

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.finding_budget import (
    FINDING_BUDGET,
    ROUND_CAP,
    FindingBudget,
    ReviewRound,
    budget_arm,
    budget_note,
    round_note,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority


def _pair(
    run_index: int, priority: IssuePriority, *, valid: bool = True
) -> tuple[ReviewIssueFinding, ValidationVerdict | None]:
    key = f"r{run_index}:a.py:1:flash-single-agent:{priority.value}-{valid}"
    finding = ReviewIssueFinding(
        issue_key=key, run_index=run_index, title="t", file="a.py", body="b", suggestion="", priority=priority
    )
    return finding, ValidationVerdict(issue_key=key, is_valid=valid, argumentation="a")


def _report(pr_number: int | None, thresholds: dict[str, str]) -> ReviewReport:
    return ReviewReport(repository="PostHog/posthog", pr_number=pr_number, published_urgency_thresholds=thresholds)


@pytest.mark.parametrize(
    "repository,pr_number,expected",
    [
        ("PostHog/posthog", 114369, "budget"),
        ("posthog/POSTHOG", 114369, "budget"),
        ("PostHog/posthog", 116849, "control"),
        ("PostHog/posthog", None, "control"),
    ],
)
def test_budget_arm_is_stable_for_a_pull_request(repository: str, pr_number: int | None, expected: str) -> None:
    assert budget_arm(repository, pr_number) == expected


def test_budget_counts_only_findings_that_published_turns_posted() -> None:
    prior = [
        _pair(1, IssuePriority.SHOULD_FIX),
        _pair(1, IssuePriority.CONSIDER),
        _pair(1, IssuePriority.MUST_FIX, valid=False),
        _pair(2, IssuePriority.CONSIDER),
        _pair(2, IssuePriority.MUST_FIX),
        _pair(3, IssuePriority.SHOULD_FIX),
    ]
    # Turn 2 gated at must_fix, so its consider finding stayed off the PR; turn 3 never published.
    budget = FindingBudget.for_turn(_report(114369, {"1": "consider", "2": "must_fix"}), prior)

    assert (budget.posted_before, budget.left) == (3, FINDING_BUDGET - 3)


def test_control_arm_has_no_budget() -> None:
    budget = FindingBudget.for_turn(_report(116849, {"1": "consider"}), [_pair(1, IssuePriority.SHOULD_FIX)])

    assert (budget.arm, budget.left) == ("control", None)


@pytest.mark.parametrize("comment_commands_on,offers_deep", [(True, True), (False, False)])
def test_budget_note_offers_only_a_review_that_runs_on_this_head(comment_commands_on: bool, offers_deep: bool) -> None:
    # The head already has its Standard review, so a second Standard request would be refused.
    note = budget_note(3, comment_commands_on)

    assert note.startswith("This pull request reached its limit of 20 automatic review findings")
    assert ("`@posthog review --deep`" in note) is offers_deep
    assert "`@posthog review` " not in note


@pytest.mark.parametrize(
    "published_head_shas,run_index,expected_number,asks_for_a_rethink",
    [
        (None, 1, 1, False),
        # Turn 2 kept nothing, so turn 3 is still round 2.
        ({"1": "a"}, 3, 2, False),
        ({"1": "a", "2": "b"}, 3, 3, True),
        # Read after this turn published: its own key does not count twice.
        ({"1": "a", "2": "b", "3": "c"}, 3, 3, True),
        ({"1": "a", "2": "b", "3": "c", "5": "e"}, 6, 5, True),
    ],
)
def test_review_round_counts_the_turns_that_published_before_this_one(
    published_head_shas: dict[str, str] | None, run_index: int, expected_number: int, asks_for_a_rethink: bool
) -> None:
    report = ReviewReport(repository="PostHog/posthog", pr_number=1, published_head_shas=published_head_shas)

    review_round = ReviewRound.for_turn(report, run_index=run_index)

    assert (review_round.number, review_round.asks_for_a_rethink) == (expected_number, asks_for_a_rethink)


def test_round_note_names_the_round() -> None:
    assert round_note(ReviewRound(number=ROUND_CAP)).startswith(
        f"This is review round {ROUND_CAP} on this pull request."
    )
