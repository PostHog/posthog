from dataclasses import replace

import pytest

from products.tasks.backend.logic.code_workstreams.classify import (
    STALE_THRESHOLD_MS,
    ClassifyInput,
    ClassifyPr,
    classify,
    pick_primary_situation,
)

NOW = 1_700_000_000_000


def _pr(**overrides) -> ClassifyPr:
    return replace(
        ClassifyPr(
            state="open",
            ci_status="passing",
            review_decision=None,
            unresolved_threads=0,
            is_current_user_author=True,
            mergeable=True,
        ),
        **overrides,
    )


def _input(**overrides) -> ClassifyInput:
    return replace(
        ClassifyInput(
            has_pr_url=False,
            pr=None,
            branch=None,
            last_activity_at=NOW,
            now=NOW,
        ),
        **overrides,
    )


@pytest.mark.parametrize("state", ["merged", "closed"])
def test_terminal_pr_state_is_done_and_exclusive(state):
    assert classify(_input(pr=_pr(state=state, ci_status="failing"))) == {"done"}


def test_failing_ci_open_pr():
    assert classify(_input(pr=_pr(ci_status="failing"))) == {"ci_failing", "in_review"}


def test_changes_requested():
    result = classify(_input(pr=_pr(review_decision="changes_requested")))
    assert result == {"changes_requested", "in_review"}


@pytest.mark.parametrize("is_current_user_author,expected", [(True, True), (False, False)])
def test_comments_waiting_only_for_author(is_current_user_author, expected):
    result = classify(_input(pr=_pr(unresolved_threads=2, is_current_user_author=is_current_user_author)))
    assert ("comments_waiting" in result) is expected


@pytest.mark.parametrize("mergeable,expected", [(True, True), (False, False)])
def test_ready_to_merge_requires_mergeable(mergeable, expected):
    result = classify(_input(pr=_pr(review_decision="approved", ci_status="passing", mergeable=mergeable)))
    assert ("ready_to_merge" in result) is expected


def test_pr_url_without_data_is_in_review():
    assert classify(_input(has_pr_url=True, pr=None)) == {"in_review"}


@pytest.mark.parametrize("commits_ahead,expected", [(3, {"working"}), (None, {"working"}), (0, set())])
def test_branch_with_commits_is_working(commits_ahead, expected):
    assert classify(_input(branch="feat/x", commits_ahead=commits_ahead)) == expected


def test_stale_stacks_on_top():
    old = NOW - STALE_THRESHOLD_MS - 1
    result = classify(_input(pr=_pr(ci_status="failing"), last_activity_at=old))
    assert "stale" in result
    assert "ci_failing" in result


def test_stale_never_stacks_on_done():
    old = NOW - STALE_THRESHOLD_MS - 1
    result = classify(_input(pr=_pr(state="merged"), last_activity_at=old))
    assert result == {"done"}


@pytest.mark.parametrize(
    "situations,expected",
    [
        ({"working", "ci_failing", "stale"}, "ci_failing"),
        ({"stale", "working"}, "working"),
        (set(), None),
    ],
)
def test_pick_primary_situation_priority(situations, expected):
    assert pick_primary_situation(situations) == expected
