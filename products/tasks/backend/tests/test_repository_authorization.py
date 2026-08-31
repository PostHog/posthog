import time

from django.test import TestCase
from django.test.utils import override_settings

from posthog.models import Integration, Organization, Team, User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.facade import (
    api as tasks_api,
    contracts,
)


class TestRepositoryAuthorization(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Repository authorization org")
        self.team = Team.objects.create(organization=self.organization, name="Repository authorization team")
        self.user = User.objects.create_user(email="author@example.com", first_name="Author", password="password")
        self.organization.members.add(self.user)

    def _create_personal_integration(
        self,
        *,
        installation_id: str = "installation-1",
        repositories: list[dict[str, object]] | None = None,
        usable: bool = True,
    ) -> UserIntegration:
        now = int(time.time())
        return UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id=installation_id,
            config={
                "user_token_refreshed_at": now,
                "user_access_token_expires_at": now + 3600 if usable else now - 3600,
                "user_refresh_token_expires_at": now + 3600,
            },
            sensitive_config={
                "user_access_token": "access" if usable else "",
                "user_refresh_token": "refresh" if usable else "",
            },
            repository_cache=repositories
            or [
                {
                    "id": 1,
                    "name": "repo",
                    "full_name": "owner/repo",
                    "can_push": True,
                    "private": True,
                    "visibility": "private",
                },
                {
                    "id": 2,
                    "name": "read-only",
                    "full_name": "owner/read-only",
                    "can_push": False,
                    "private": True,
                    "visibility": "private",
                },
            ],
        )

    def _create_team_integration(
        self,
        *,
        installation_id: str = "installation-1",
        repositories: list[dict[str, object]] | None = None,
    ) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            integration_id=installation_id,
            config={"installation_id": installation_id},
            sensitive_config={"access_token": "installation-token"},
            repository_cache=repositories
            or [
                {
                    "id": 1,
                    "name": "repo",
                    "full_name": "owner/repo",
                    "can_push": True,
                    "private": True,
                    "visibility": "private",
                },
                {
                    "id": 2,
                    "name": "read-only",
                    "full_name": "owner/read-only",
                    "can_push": False,
                    "private": True,
                    "visibility": "private",
                },
            ],
        )

    def test_lists_only_repositories_writable_by_the_user_and_team_installation(self) -> None:
        self._create_personal_integration()
        team_integration = self._create_team_integration()

        repositories = tasks_api.list_authorizable_repositories(team_id=self.team.id, user_id=self.user.id)

        self.assertEqual(
            repositories,
            [
                contracts.AuthorizableRepositoryDTO(
                    repository="owner/repo",
                    github_integration_id=team_integration.id,
                    github_installation_id="installation-1",
                )
            ],
        )

    @override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=[])
    def test_excludes_public_repositories_without_an_explicit_allowlist_entry(self) -> None:
        public_repository = {
            "id": 1,
            "name": "public-repo",
            "full_name": "owner/public-repo",
            "can_push": True,
            "private": False,
            "visibility": "public",
        }
        self._create_personal_integration(repositories=[public_repository])
        self._create_team_integration(repositories=[public_repository])

        self.assertEqual(
            tasks_api.list_authorizable_repositories(team_id=self.team.id, user_id=self.user.id),
            [],
        )

    @override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=["OWNER/PUBLIC-REPO"])
    def test_allows_an_explicitly_allowlisted_public_repository(self) -> None:
        public_repository = {
            "id": 1,
            "name": "public-repo",
            "full_name": "owner/public-repo",
            "can_push": True,
            "private": False,
            "visibility": "public",
        }
        self._create_personal_integration(repositories=[public_repository])
        team_integration = self._create_team_integration(repositories=[public_repository])

        self.assertEqual(
            tasks_api.list_authorizable_repositories(team_id=self.team.id, user_id=self.user.id),
            [
                contracts.AuthorizableRepositoryDTO(
                    repository="owner/public-repo",
                    github_integration_id=team_integration.id,
                    github_installation_id="installation-1",
                )
            ],
        )

    @override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=[])
    def test_allows_private_repositories_without_a_public_allowlist_entry(self) -> None:
        private_repository = {
            "id": 1,
            "name": "private-repo",
            "full_name": "owner/private-repo",
            "can_push": True,
            "private": True,
            "visibility": "private",
        }
        self._create_personal_integration(repositories=[private_repository])
        team_integration = self._create_team_integration(repositories=[private_repository])

        self.assertEqual(
            tasks_api.list_authorizable_repositories(team_id=self.team.id, user_id=self.user.id),
            [
                contracts.AuthorizableRepositoryDTO(
                    repository="owner/private-repo",
                    github_integration_id=team_integration.id,
                    github_installation_id="installation-1",
                )
            ],
        )

    def test_resolves_only_the_canonical_writable_repository_binding(self) -> None:
        self._create_personal_integration()
        team_integration = self._create_team_integration()

        binding = tasks_api.resolve_repository_authorization(
            team_id=self.team.id,
            user_id=self.user.id,
            repository="OWNER/REPO",
        )

        self.assertEqual(
            binding,
            contracts.AuthorizableRepositoryDTO(
                repository="owner/repo",
                github_integration_id=team_integration.id,
                github_installation_id="installation-1",
            ),
        )

    def test_refuses_missing_write_access_unusable_user_or_unmatched_team_installation(self) -> None:
        self._create_personal_integration(usable=False)
        self._create_team_integration()

        self.assertIsNone(
            tasks_api.resolve_repository_authorization(
                team_id=self.team.id,
                user_id=self.user.id,
                repository="owner/repo",
            )
        )

        UserIntegration.objects.filter(user=self.user).delete()
        self._create_personal_integration()
        Integration.objects.filter(team=self.team).delete()
        self._create_team_integration(installation_id="another-installation")
        self.assertIsNone(
            tasks_api.resolve_repository_authorization(
                team_id=self.team.id,
                user_id=self.user.id,
                repository="owner/repo",
            )
        )

        Integration.objects.filter(team=self.team).delete()
        self._create_team_integration(
            repositories=[{"id": 1, "name": "repo", "full_name": "owner/repo", "can_push": False}]
        )
        self.assertIsNone(
            tasks_api.resolve_repository_authorization(
                team_id=self.team.id,
                user_id=self.user.id,
                repository="owner/repo",
            )
        )

    def test_refuses_ambiguous_repository_bindings(self) -> None:
        self._create_personal_integration(installation_id="installation-1")
        self._create_personal_integration(installation_id="installation-2")
        first_integration = self._create_team_integration(installation_id="installation-1")
        self._create_team_integration(installation_id="installation-2")

        self.assertIsNone(
            tasks_api.resolve_repository_authorization(
                team_id=self.team.id,
                user_id=self.user.id,
                repository="owner/repo",
            )
        )
        self.assertEqual(
            tasks_api.resolve_repository_authorization(
                team_id=self.team.id,
                user_id=self.user.id,
                repository="owner/repo",
                github_integration_id=first_integration.id,
            ),
            contracts.AuthorizableRepositoryDTO(
                repository="owner/repo",
                github_integration_id=first_integration.id,
                github_installation_id="installation-1",
            ),
        )
