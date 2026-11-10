from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration.gitlab import GitLabProject, GitLabTokenInfo

from products.tasks.backend.gitlab_repository_access import gitlab_repository_error


class TestGitLabRepositoryError:
    @parameterized.expand(
        [
            ("connected_project", "Acme/App", True, None),
            ("other_project_the_token_reaches", "acme/private-billing", True, "covers acme/app only"),
            ("token_reaching_more_projects", "acme/app", False, "need a project access token"),
        ]
    )
    def test_only_the_connected_project_is_usable(
        self, _name: str, repository: str, token_bound: bool, expected: str | None
    ) -> None:
        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "path_with_namespace": "acme/app"},
            sensitive_config={"access_token": "token123"},
        )
        project = GitLabProject(
            id=7, path_with_namespace="acme/app", web_url="https://gitlab.com/acme/app", default_branch="main"
        )
        with (
            patch(
                "posthog.models.integration.gitlab.PastedTokenSource.describe",
                return_value=GitLabTokenInfo(scopes=("api",), expires_at=None),
            ),
            patch(
                "posthog.models.integration.gitlab.GitLabIntegration.get_pushable_project", return_value=project
            ) as get_project,
            patch(
                "posthog.models.integration.gitlab.GitLabIntegration.token_reaches_only_connected_project",
                return_value=token_bound,
            ),
        ):
            error = gitlab_repository_error(integration, repository)

        if expected is None:
            assert error is None
        else:
            assert error is not None and expected in error
        if repository.lower() != "acme/app":
            get_project.assert_not_called()
