from posthog.test.base import BaseTest
from unittest import mock

from products.engineering_analytics.backend.facade import api

_LOGIC = "products.engineering_analytics.backend.facade.api.logic"


class TestEngineeringAnalyticsFacade(BaseTest):
    def test_get_pr_lifecycle_delegates_with_defaults(self) -> None:
        with mock.patch(f"{_LOGIC}.build_pr_lifecycle", return_value=None) as build:
            assert api.get_pr_lifecycle(team=self.team, pr_number=10) is None

        build.assert_called_once_with(team=self.team, pr_number=10, repo=None)

    def test_get_pr_lifecycle_forwards_repo(self) -> None:
        with mock.patch(f"{_LOGIC}.build_pr_lifecycle", return_value="sentinel") as build:
            result = api.get_pr_lifecycle(team=self.team, pr_number=42, repo="PostHog/posthog")

        assert result == "sentinel"
        build.assert_called_once_with(team=self.team, pr_number=42, repo="PostHog/posthog")
