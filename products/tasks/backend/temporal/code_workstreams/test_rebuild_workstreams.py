import pytest

from products.tasks.backend.models import CodePrSnapshot
from products.tasks.backend.temporal.code_workstreams.activities.rebuild_workstreams import _build_pr_input


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
