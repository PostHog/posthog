from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.egress.limiter.policies import Priority

from products.review_hog.backend.reviewer.tools.github_client import (
    GitHubAPIError,
    add_pr_reaction,
    github_api_request,
    remove_own_pr_reactions,
)

_MODULE = "products.review_hog.backend.reviewer.tools.github_client"


def test_requests_ride_the_normal_priority_lane() -> None:
    # The transport default is CRITICAL (never shed). ReviewHog is an automated workload sharing the
    # installation budget with interactive callers — a revert to the default would let review
    # pagination burn the reserve kept for user-facing traffic under budget pressure.
    mock_transport = MagicMock(return_value=MagicMock(ok=True))
    with patch(f"{_MODULE}.github_request", mock_transport), patch(f"{_MODULE}.raise_if_github_rate_limited"):
        github_api_request("GET", "/repos/o/r", token="t", endpoint="/repos/{owner}/{repo}")

    assert mock_transport.call_args.kwargs["priority"] is Priority.NORMAL


def test_add_pr_reaction_fails_open() -> None:
    # The reaction is a signal on the PR. A GitHub error here must never fail the review activity.
    with patch(f"{_MODULE}.github_api_request", side_effect=GitHubAPIError("no", status=403)):
        assert add_pr_reaction("o/r", 7, "eyes", token="t") is None


@override_settings(REVIEWHOG_GITHUB_BOT_LOGIN="posthog[bot]")
def test_remove_own_pr_reactions_deletes_only_the_apps_reactions_and_fails_open() -> None:
    reactions = [
        {"id": 1, "content": "+1", "user": {"login": "octocat", "type": "User"}},
        {"id": 2, "content": "+1", "user": {"login": "greptile-apps[bot]", "type": "Bot"}},
        {"id": 3, "content": "+1", "user": {"login": "posthog[bot]", "type": "Bot"}},
        {"id": 4, "content": "+1", "user": {"login": "posthog[bot]", "type": "Bot"}},
    ]
    with (
        patch(f"{_MODULE}.github_api_get_paginated", return_value=iter(reactions)) as mock_paginated,
        patch(f"{_MODULE}.github_api_request", side_effect=[GitHubAPIError("boom", status=500), None]) as mock_request,
    ):
        remove_own_pr_reactions("o/r", 7, "+1", token="t")

    assert mock_paginated.call_args.kwargs["params"] == {"content": "+1"}
    # The first delete fails and the second one still runs.
    assert [c.args for c in mock_request.call_args_list] == [
        ("DELETE", "/repos/o/r/issues/7/reactions/3"),
        ("DELETE", "/repos/o/r/issues/7/reactions/4"),
    ]
