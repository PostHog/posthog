from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from products.engineering_analytics.backend.facade import api

_LOGIC = "products.engineering_analytics.backend.facade.api.logic"
_FOR_TEAM = f"{_LOGIC}.CuratedGitHubSource.for_team"


class TestEngineeringAnalyticsFacade(BaseTest):
    @parameterized.expand(
        [
            # Each facade function resolves the authorized handle once (for_team, given the caller's
            # source_id + access control) and delegates the handle plus its own params to the builder.
            (
                "pr_lifecycle_defaults",
                api.get_pr_lifecycle,
                "build_pr_lifecycle",
                {"pr_number": 10},
                {"source_id": None, "user_access_control": None},
                {"pr_number": 10, "repo": None},
            ),
            (
                "pr_lifecycle_forwards_repo_source_and_access",
                api.get_pr_lifecycle,
                "build_pr_lifecycle",
                {
                    "pr_number": 42,
                    "repo": "PostHog/posthog",
                    "source_id": "abc",
                    "user_access_control": mock.sentinel.uac,
                },
                {"source_id": "abc", "user_access_control": mock.sentinel.uac},
                {"pr_number": 42, "repo": "PostHog/posthog"},
            ),
            (
                "ci_cards",
                api.get_ci_cards,
                "build_ci_cards",
                {"source_id": "abc"},
                {"source_id": "abc", "user_access_control": None},
                {},
            ),
            (
                "pull_requests",
                api.list_pull_requests,
                "build_pull_request_list",
                {"date_from": "-7d", "source_id": "abc"},
                {"source_id": "abc", "user_access_control": None},
                {"date_from": "-7d"},
            ),
            (
                "workflow_health",
                api.list_workflow_health,
                "build_workflow_health",
                {"date_from": "-7d", "date_to": "-1d", "source_id": "abc"},
                {"source_id": "abc", "user_access_control": None},
                {"date_from": "-7d", "date_to": "-1d"},
            ),
        ]
    )
    def test_resolves_authorized_handle_then_delegates(
        self, _name, facade_fn, build_name, call_kwargs, expected_for_team, expected_build
    ) -> None:
        with (
            mock.patch(_FOR_TEAM, return_value=mock.sentinel.curated) as for_team,
            mock.patch(f"{_LOGIC}.{build_name}", return_value=mock.sentinel.result) as build,
        ):
            result = facade_fn(team=self.team, **call_kwargs)

        assert result is mock.sentinel.result
        for_team.assert_called_once_with(self.team, **expected_for_team)
        build.assert_called_once_with(curated=mock.sentinel.curated, **expected_build)

    def test_list_github_sources_delegates_with_access(self) -> None:
        with mock.patch(f"{_LOGIC}.build_github_sources", return_value=mock.sentinel.result) as build:
            result = api.list_github_sources(team=self.team, user_access_control=mock.sentinel.uac)

        assert result is mock.sentinel.result
        build.assert_called_once_with(team=self.team, user_access_control=mock.sentinel.uac)
