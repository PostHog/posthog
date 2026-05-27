from posthog.test.base import BaseTest
from unittest import mock

from products.engineering_analytics.backend.facade import api

_LOGIC = "products.engineering_analytics.backend.facade.api.logic"


class TestEngineeringAnalyticsFacade(BaseTest):
    def test_get_workflow_report_delegates_with_defaults(self) -> None:
        with mock.patch(f"{_LOGIC}.build_workflow_report", return_value="sentinel") as build:
            result = api.get_workflow_report(team=self.team)

        assert result == "sentinel"
        build.assert_called_once_with(team=self.team, date_from="-7d", date_to=None, repo=None)

    def test_get_time_to_merge_forwards_arguments(self) -> None:
        with mock.patch(f"{_LOGIC}.build_time_to_merge", return_value="sentinel") as build:
            api.get_time_to_merge(
                team=self.team,
                date_from="-30d",
                date_to="2026-01-01",
                repo="PostHog/posthog",
                group_by_author=True,
            )

        build.assert_called_once_with(
            team=self.team,
            date_from="-30d",
            date_to="2026-01-01",
            repo="PostHog/posthog",
            group_by_author=True,
        )

    def test_get_pr_lifecycle_delegates(self) -> None:
        with mock.patch(f"{_LOGIC}.build_pr_lifecycle", return_value=None) as build:
            assert api.get_pr_lifecycle(team=self.team, pr_number=10) is None

        build.assert_called_once_with(team=self.team, pr_number=10, repo=None)
