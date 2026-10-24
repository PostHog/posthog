from django.test import SimpleTestCase, override_settings

from posthog.egress.limiter.policies import resolve_policy

from products.error_tracking.backend.logic.repo_paths.fetch_budget import GitFetchBudgetOwner


class TestGitFetchBudget(SimpleTestCase):
    @override_settings(ERROR_TRACKING_GIT_FETCH_PER_MINUTE_BUDGET=3, ERROR_TRACKING_GIT_FETCH_HOURLY_BUDGET=7)
    def test_budget_reads_its_settings(self) -> None:
        key = GitFetchBudgetOwner(provider="github", owner_id="123").limiter_key()

        assert resolve_policy(key).limits == ((3, 60.0), (7, 3600.0))
