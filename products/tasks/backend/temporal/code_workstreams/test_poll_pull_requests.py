from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError

from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import PrRef
from products.tasks.backend.temporal.code_workstreams.activities.poll_pull_requests import poll_pull_requests_for_team

_RESOLVE = "products.tasks.backend.temporal.code_workstreams.activities.poll_pull_requests._resolve_integration"


def _refs(count: int) -> list[PrRef]:
    return [
        PrRef(
            pr_url=f"https://github.com/acme/widgets/pull/{n}", github_integration_id=1, github_user_integration_id=None
        )
        for n in range(1, count + 1)
    ]


# Guards the shed/backoff seam: if either exception stops being caught here, the whole team sweep
# activity fails and Temporal re-runs it immediately — hammering the budget it was just shed from —
# instead of yielding until the next scheduled cycle.
@parameterized.expand(
    [
        ("egress_budget_shed", GitHubEgressBudgetExhausted("shed")),
        ("github_rate_limited", GitHubRateLimitError("429", retry_after=60)),
    ]
)
def test_poll_stops_the_cycle_when_shed_or_rate_limited(_name: str, exc: Exception) -> None:
    integration = MagicMock()
    integration.get_pull_request_snapshot.side_effect = exc

    with patch(_RESOLVE, return_value=integration):
        result = poll_pull_requests_for_team(1, _refs(3))

    assert result.rate_limited is True
    assert result.polled == 0
    # break, not continue: one attempt, then yield the remaining PRs to the next cycle
    integration.get_pull_request_snapshot.assert_called_once()
