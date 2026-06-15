from posthog.test.base import BaseTest
from unittest import mock

from products.engineering_analytics.backend.facade import api

_LOGIC = "products.engineering_analytics.backend.facade.api.logic"


class TestEngineeringAnalyticsFacade(BaseTest):
    def test_get_pr_lifecycle_delegates_with_defaults(self) -> None:
        with mock.patch(f"{_LOGIC}.build_pr_lifecycle", return_value=None) as build:
            assert api.get_pr_lifecycle(team=self.team, pr_number=10) is None

        build.assert_called_once_with(team=self.team, pr_number=10, repo=None, source_id=None)

    def test_get_pr_lifecycle_forwards_repo_and_source_id(self) -> None:
        with mock.patch(f"{_LOGIC}.build_pr_lifecycle", return_value=mock.sentinel.result) as build:
            result = api.get_pr_lifecycle(team=self.team, pr_number=42, repo="PostHog/posthog", source_id="abc")

        assert result is mock.sentinel.result
        build.assert_called_once_with(team=self.team, pr_number=42, repo="PostHog/posthog", source_id="abc")

    def test_get_ci_cards_forwards_source_id(self) -> None:
        with mock.patch(f"{_LOGIC}.build_ci_cards", return_value=mock.sentinel.result) as build:
            assert api.get_ci_cards(team=self.team, source_id="abc") is mock.sentinel.result

        build.assert_called_once_with(team=self.team, source_id="abc")

    def test_list_pull_requests_forwards_date_from_and_source_id(self) -> None:
        with mock.patch(f"{_LOGIC}.build_pull_request_list", return_value=[]) as build:
            api.list_pull_requests(team=self.team, date_from="-7d", source_id="abc")

        build.assert_called_once_with(team=self.team, date_from="-7d", source_id="abc")

    def test_list_workflow_health_forwards_window_and_source_id(self) -> None:
        with mock.patch(f"{_LOGIC}.build_workflow_health", return_value=[]) as build:
            api.list_workflow_health(team=self.team, date_from="-7d", date_to="-1d", source_id="abc")

        build.assert_called_once_with(team=self.team, date_from="-7d", date_to="-1d", source_id="abc")
