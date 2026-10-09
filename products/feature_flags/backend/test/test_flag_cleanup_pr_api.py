from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade import api as tasks_facade

MULTIVARIATE_FILTERS = {
    "groups": [{"properties": [], "rollout_percentage": 100}],
    "multivariate": {
        "variants": [
            {"key": "control", "rollout_percentage": 50},
            {"key": "test", "rollout_percentage": 50},
        ]
    },
}


def _github(repositories: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        list_all_cached_repositories=lambda max_repos: [{"full_name": name} for name in repositories]
    )


class TestFeatureFlagCleanupPrApi(APIBaseTest):
    def _flag(self, *, archived: bool = True, filters: dict | None = None) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="cleanup-flag",
            created_by=self.user,
            archived=archived,
            active=not archived,
            filters=filters or {"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def _url(self, flag: FeatureFlag, action: str) -> str:
        return f"/api/projects/{self.team.id}/feature_flags/{flag.id}/{action}/"

    @parameterized.expand(
        [
            ("boolean_enabled", None, {"keep": "enabled"}, "Keep the code path that runs when the flag is enabled."),
            ("boolean_disabled", None, {"keep": "disabled"}, "Keep the code path that runs when the flag is disabled."),
            (
                "multivariate_variant",
                MULTIVARIATE_FILTERS,
                {"keep": "variant", "variant_key": "test"},
                'Keep the code path for variant "test".',
            ),
        ]
    )
    @patch("products.tasks.backend.facade.api.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_opens_cleanup_task_keeping_chosen_path(
        self, _name, filters, body, expected_instruction, mock_resolve_github, mock_create_task
    ):
        mock_resolve_github.return_value = _github(["posthog/posthog"])
        task_id = uuid4()
        mock_create_task.return_value = SimpleNamespace(task_id=task_id)
        flag = self._flag(filters=filters)

        response = self.client.post(self._url(flag, "cleanup_pr"), body)

        assert response.status_code == 200, response.json()
        assert response.json() == {"task_id": str(task_id), "repository": "posthog/posthog"}
        kwargs = mock_create_task.call_args.kwargs
        assert kwargs["repository"] == "posthog/posthog"
        assert kwargs["create_pr"] is True
        assert kwargs["origin_product"] == tasks_facade.TaskOriginProduct.USER_CREATED
        assert expected_instruction in kwargs["description"]

    @parameterized.expand(
        [
            ("not_archived", False, None, {"keep": "enabled"}, ["posthog/posthog"], "archive"),
            (
                "variant_without_key",
                True,
                MULTIVARIATE_FILTERS,
                {"keep": "variant"},
                ["posthog/posthog"],
                "variant_key",
            ),
            (
                "unknown_variant",
                True,
                MULTIVARIATE_FILTERS,
                {"keep": "variant", "variant_key": "nope"},
                ["posthog/posthog"],
                "variant_key",
            ),
            ("enabled_on_multivariate", True, MULTIVARIATE_FILTERS, {"keep": "enabled"}, ["posthog/posthog"], "keep"),
            (
                "several_repositories",
                True,
                None,
                {"keep": "enabled"},
                ["posthog/posthog", "posthog/other"],
                "repository",
            ),
            (
                "repository_outside_installation",
                True,
                None,
                {"keep": "enabled", "repository": "someone/else"},
                ["posthog/posthog", "posthog/other"],
                "repository",
            ),
        ]
    )
    @patch("products.tasks.backend.facade.api.create_and_run_task")
    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_rejects_requests_that_cannot_produce_a_safe_cleanup(
        self, _name, archived, filters, body, repositories, expected_error, mock_resolve_github, mock_create_task
    ):
        mock_resolve_github.return_value = _github(repositories)
        flag = self._flag(archived=archived, filters=filters)

        response = self.client.post(self._url(flag, "cleanup_pr"), body)

        assert response.status_code == 400
        assert expected_error in str(response.json()).lower()
        mock_create_task.assert_not_called()

    @patch("products.tasks.backend.facade.repo_selection.resolve_team_github_integration")
    def test_cleanup_target_reports_candidates(self, mock_resolve_github):
        mock_resolve_github.return_value = _github(["posthog/posthog", "posthog/other"])
        flag = self._flag()

        response = self.client.get(self._url(flag, "cleanup_target"))

        assert response.status_code == 200
        assert response.json() == {
            "repository": None,
            "source": "ambiguous",
            "candidates": ["posthog/other", "posthog/posthog"],
        }
