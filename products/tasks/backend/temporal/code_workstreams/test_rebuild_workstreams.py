from datetime import UTC, datetime

import pytest

from products.tasks.backend.models import CodePrSnapshot
from products.tasks.backend.temporal.code_workstreams.activities.rebuild_workstreams import (
    _branch_resolution_pref,
    _build_pr_input,
    _repo_from_pr_url,
)
from products.tasks.backend.temporal.process_task.utils import parse_run_state


def _snapshot(**overrides) -> CodePrSnapshot:
    defaults = {
        "pr_url": "https://github.com/org/repo/pull/1",
        "number": 1,
        "title": "PR",
        "state": "open",
        "ci_status": "passing",
        "review_decision": None,
        "unresolved_threads": 2,
        "mergeable": True,
        "author_login": "octocat",
        "requested_reviewer_logins": ["reviewer1"],
        "pr_updated_at": None,
    }
    defaults.update(overrides)
    return CodePrSnapshot(**defaults)


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"pr_base_branch": "master"}, "master"),
        ({"pr_base_branch": "main", "mode": "background"}, "main"),
        ({"mode": "background"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_parse_run_state_reads_pr_base_branch(state, expected):
    assert parse_run_state(state).pr_base_branch == expected


@pytest.mark.parametrize(
    "pr_url,expected",
    [
        ("https://github.com/posthog/posthog/pull/123", "posthog/posthog"),
        ("https://github.com/owner/repo/pull/1", "owner/repo"),
        ("https://github.enterprise.com/posthog/posthog/pull/9", "posthog/posthog"),
        ("not-a-url", None),
        ("https://github.com/onlyowner", None),
    ],
)
def test_repo_from_pr_url(pr_url, expected):
    assert _repo_from_pr_url(pr_url) == expected


def test_build_pr_input_carries_head_branch():
    pr = _build_pr_input(_snapshot(head_branch="feat/x"), set())
    assert pr.head_branch == "feat/x"


def test_branch_resolution_pref_prefers_open_then_recent():
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    closed_new = _snapshot(pr_url="c", state="closed", pr_updated_at=new)
    open_old = _snapshot(pr_url="a", state="open", pr_updated_at=old)
    open_new = _snapshot(pr_url="b", state="open", pr_updated_at=new)
    # Sorting ascending puts the winner last (last-wins when building the map).
    winner = sorted([closed_new, open_old, open_new], key=_branch_resolution_pref)[-1]
    assert winner.pr_url == "b"


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"home_quick_action": "Fix CI"}, "Fix CI"),
        ({"mode": "background"}, None),
        (None, None),
    ],
)
def test_parse_run_state_reads_home_quick_action(state, expected):
    assert parse_run_state(state).home_quick_action == expected


@pytest.mark.parametrize(
    "author_login,user_github_logins,expected",
    [
        ("octocat", {"octocat"}, True),
        ("octocat", {"octocat", "alt"}, True),
        ("octocat", {"someone-else"}, False),
        ("octocat", set(), False),
        (None, {"octocat"}, False),
    ],
)
def test_build_pr_input_is_author_requires_identity_match(author_login, user_github_logins, expected):
    pr = _build_pr_input(_snapshot(author_login=author_login), user_github_logins)
    assert pr.is_current_user_author is expected


@pytest.mark.parametrize(
    "requested_reviewer_logins,user_github_logins,expected",
    [
        (["alice", "bob"], {"bob"}, True),
        (["alice", "bob"], {"carol"}, False),
        ([], {"bob"}, False),
        (["alice"], set(), False),
    ],
)
def test_build_pr_input_is_requested_reviewer_requires_identity_match(
    requested_reviewer_logins, user_github_logins, expected
):
    pr = _build_pr_input(_snapshot(requested_reviewer_logins=requested_reviewer_logins), user_github_logins)
    assert pr.is_current_user_requested_reviewer is expected
