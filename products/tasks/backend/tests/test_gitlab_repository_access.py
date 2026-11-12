from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration.gitlab import GitLabProject, GitLabTokenInfo

from products.tasks.backend.gitlab_repository_access import gitlab_repository_error


class TestGitLabRepositoryError:
    @parameterized.expand(
        [
            ("connected_project", "Acme/App", None),
            ("other_project_the_token_reaches", "acme/private-billing", "covers acme/app only"),
        ]
    )
    def test_only_the_connected_project_is_usable(self, _name: str, repository: str, expected: str | None) -> None:
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
        ):
            error = gitlab_repository_error(integration, repository)

        if expected is None:
            assert error is None
        else:
            assert error is not None and expected in error
            get_project.assert_not_called()
