from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import GitHubIntegration, Integration

from products.signals.backend.github_optional import GITHUB_OPTIONAL_FLAG, ResearchAccessPolicy


class TestResearchAccessPolicy(BaseTest):
    def test_flag_uses_canonical_project_and_fails_closed(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        with patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=True) as flag:
            assert ResearchAccessPolicy.enabled(child.id)
        assert flag.call_args.args == (GITHUB_OPTIONAL_FLAG, str(self.team.uuid))
        assert flag.call_args.kwargs["groups"] == {"project": str(self.team.uuid)}
        with patch("products.signals.backend.github_optional.feature_enabled_or_false", side_effect=RuntimeError):
            assert not ResearchAccessPolicy.enabled(self.team.id)

    @parameterized.expand(
        ["example/app/contents/file", "example/app?ref=main", "example/app#section", "example/app%2Fpath"]
    )
    def test_repository_access_rejects_non_repository_paths(self, repository: str) -> None:
        Integration.objects.create(team=self.team, kind="github", integration_id="first")
        with patch.object(GitHubIntegration, "installation_can_access_repository") as probe:
            assert ResearchAccessPolicy.repository_integration_id(self.team.id, repository) is None
        probe.assert_not_called()
