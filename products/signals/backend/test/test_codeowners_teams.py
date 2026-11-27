from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.integrations import IntegrationManager
from posthog.models.integration import GitHubIntegration

from products.access_control.backend.models.role import Role
from products.access_control.backend.models.role_external_reference import RoleExternalReference
from products.signals.backend.codeowners_teams import ParsedCodeownersTeam, parse_codeowners_teams
from products.signals.backend.presentation.codeowners_teams import CodeownersTeamsQuerySerializer


class TestParseCodeownersTeams(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "standard_and_comments",
                "# Top comment\n/.github/CODEOWNERS @PostHog/team-devex # inline note\nposthog/hogql/** @PostHog/hogql @octocat dev@example.com\n",
                [
                    ParsedCodeownersTeam(provider_organization_id="posthog", team_slug="team-devex"),
                    ParsedCodeownersTeam(provider_organization_id="posthog", team_slug="hogql"),
                ],
            ),
            (
                "escaped_spaces_and_dedupe",
                "docs/my\\ folder/** @PostHog/Team-Docs @PostHog/team-docs\n!docs/secret.md @PostHog/ignored\n",
                [ParsedCodeownersTeam(provider_organization_id="posthog", team_slug="team-docs")],
            ),
            (
                "section_headers",
                "[Documentation]\n^[Approvals][2] @PostHog/team-security\n/src/ @PostHog/team-core\n",
                [
                    ParsedCodeownersTeam(provider_organization_id="posthog", team_slug="team-security"),
                    ParsedCodeownersTeam(provider_organization_id="posthog", team_slug="team-core"),
                ],
            ),
            (
                "unowned_reset_lines",
                "posthog/hogql/database/schema/**\n",
                [],
            ),
        ]
    )
    def test_parses_github_teams_in_source_order(
        self, _name: str, content: str, expected: list[ParsedCodeownersTeam]
    ) -> None:
        assert parse_codeowners_teams(content) == expected

    def test_query_serializer_rejects_oversized_repository(self) -> None:
        serializer = CodeownersTeamsQuerySerializer(data={"repository": "a" * 201})
        assert not serializer.is_valid()
        assert serializer.errors["repository"][0].code == "max_length"


class TestSignalCodeownersTeamsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = IntegrationManager.github.oauth.create(
            self.team.id,
            external_id="12345",
            config={
                "account": {"name": "PostHog", "type": "Organization"},
                "installation_id": "12345",
            },
            created_by_id=self.user.id,
        )
        self.devex_role = Role.objects.create(name="Dev Ex", organization=self.organization)
        self.cymbal_role = Role.objects.create(name="Error Tracking", organization=self.organization)
        RoleExternalReference.objects.create(
            organization=self.organization,
            role=self.cymbal_role,
            provider="github",
            provider_organization_id="posthog",
            provider_role_id="team-cymbal",
            provider_role_slug="team-cymbal",
            provider_role_name="@posthog/team-cymbal",
            created_by=self.user,
        )

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/codeowners_teams/"

    def test_scans_connected_repositories_and_resolves_likely_roles(self) -> None:
        codeowners_text = (
            "/.github/CODEOWNERS @PostHog/team-devex\n"
            "rust/cymbal/** @PostHog/team-cymbal\n"
            "products/unknown/** @PostHog/unmapped-squad\n"
        )
        with (
            patch.object(
                GitHubIntegration,
                "list_all_cached_repositories",
                return_value=[
                    {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
                    {"id": 2, "name": "archived-repo", "full_name": "PostHog/archived-repo", "archived": True},
                ],
            ),
            patch(
                "products.signals.backend.codeowners_teams.AuthenticatedRepoFiles.read_all",
            ),
            patch(
                "products.signals.backend.codeowners_teams.AuthenticatedRepoFiles.read",
                side_effect=lambda loc: codeowners_text if loc == ".github/CODEOWNERS" else None,
            ),
        ):
            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["scanned_repository_count"] == 1
        assert body["total_repository_count"] == 1
        assert body["teams"] == [
            {
                "provider_organization_id": "posthog",
                "team_slug": "team-cymbal",
                "handle": "@posthog/team-cymbal",
                "repositories": ["PostHog/posthog"],
                "likely_role_id": str(self.cymbal_role.id),
                "likely_role_name": "Error Tracking",
                "match_source": "external_reference",
            },
            {
                "provider_organization_id": "posthog",
                "team_slug": "team-devex",
                "handle": "@posthog/team-devex",
                "repositories": ["PostHog/posthog"],
                "likely_role_id": str(self.devex_role.id),
                "likely_role_name": "Dev Ex",
                "match_source": "name_match",
            },
            {
                "provider_organization_id": "posthog",
                "team_slug": "unmapped-squad",
                "handle": "@posthog/unmapped-squad",
                "repositories": ["PostHog/posthog"],
                "likely_role_id": None,
                "likely_role_name": None,
                "match_source": None,
            },
        ]

    @parameterized.expand(
        [
            ("invalid_format", "not-a-repo"),
            ("unreachable_repo", "other-org/private-repo"),
        ]
    )
    def test_rejects_invalid_or_unreachable_repository_parameter(self, _name: str, repo_param: str) -> None:
        with patch(
            "products.signals.backend.codeowners_teams.GitHubIntegration.first_for_team_repository",
            return_value=MagicMock() if repo_param == "PostHog/posthog" else None,
        ):
            response = self.client.get(self._url(), data={"repository": repo_param})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "detail" in response.json()
