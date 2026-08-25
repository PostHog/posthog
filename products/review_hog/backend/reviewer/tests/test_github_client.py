from unittest.mock import MagicMock, patch

from posthog.egress.limiter.policies import Priority

from products.review_hog.backend.reviewer.tools.github_client import github_api_request

_MODULE = "products.review_hog.backend.reviewer.tools.github_client"


def test_requests_ride_the_normal_priority_lane() -> None:
    # The transport default is CRITICAL (never shed). ReviewHog is an automated workload sharing the
    # installation budget with interactive callers — a revert to the default would let review
    # pagination burn the reserve kept for user-facing traffic under budget pressure.
    mock_transport = MagicMock(return_value=MagicMock(ok=True))
    with patch(f"{_MODULE}.github_request", mock_transport), patch(f"{_MODULE}.raise_if_github_rate_limited"):
        github_api_request("GET", "/repos/o/r", token="t", endpoint="/repos/{owner}/{repo}")

    assert mock_transport.call_args.kwargs["priority"] is Priority.NORMAL
