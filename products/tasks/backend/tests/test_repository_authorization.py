from __future__ import annotations

import time
from typing import get_type_hints
from uuid import UUID

from unittest.mock import MagicMock, call, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from posthog.models import Integration, Organization, OrganizationMembership, Team, User
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.facade.repository_authorization import (
    AuthorizableRepository,
    ResolvedStagedRepositoryBinding,
    list_authorizable_repositories,
    resolve_staged_repository_binding,
)


class TestRepositoryAuthorization(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Repository authorization org")
        self.team = Team.objects.create(organization=self.organization, name="Repository authorization team")
        self.other_team = Team.objects.create(
            organization=self.organization, name="Other repository authorization team"
        )
        self.user = User.objects.create_user(email="author@example.com", first_name="Author", password="password")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)

    @staticmethod
    def _repository(
        full_name: str = "owner/repository", *, can_push: bool = True, private: bool = True
    ) -> dict[str, object]:
        return {
            "full_name": full_name,
            "can_push": can_push,
            "private": private,
            "visibility": "private" if private else "public",
        }

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
                "user_access_token_expires_at": now + 3600 if usable else now - 1,
                "user_refresh_token_expires_at": now + 3600 if usable else now - 1,
            },
            sensitive_config={
                "user_access_token": "access" if usable else "",
                "user_refresh_token": "refresh" if usable else "",
            },
            repository_cache=repositories if repositories is not None else [self._repository()],
        )

    @staticmethod
    def _create_team_integration(
        team: Team,
        *,
        installation_id: str = "installation-1",
        repositories: list[dict[str, object]] | None = None,
    ) -> Integration:
        return Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.GITHUB,
            integration_id=installation_id,
            config={"installation_id": installation_id},
            sensitive_config={"access_token": "installation-token"},
            repository_cache=repositories if repositories is not None else [TestRepositoryAuthorization._repository()],
        )

    def _resolve(self, *, repository: str = "owner/repository", github_integration_id: int | None = None):
        return resolve_staged_repository_binding(
            team_id=self.team.id,
            actor_id=self.user.id,
            repository=repository,
            github_integration_id=github_integration_id,
        )

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_lists_intersected_write_repositories_and_resolves_a_live_base(self, mock_get: MagicMock) -> None:
        personal = self._create_personal_integration()
        team_integration = self._create_team_integration(
            self.team,
            repositories=[self._repository(), self._repository("owner/read-only", can_push=False)],
        )
        mock_get.side_effect = [
            {
                "full_name": "owner/repository",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
            },
            {"commit": {"sha": "a" * 40}},
        ]

        repositories = list_authorizable_repositories(team_id=self.team.id, actor_id=self.user.id)

        assert repositories == (
            AuthorizableRepository(
                repository="owner/repository",
                github_integration_id=team_integration.id,
                github_user_integration_id=personal.id,
                github_installation_id="installation-1",
            ),
        )
        binding = self._resolve(repository="OWNER/REPOSITORY")
        assert isinstance(binding, ResolvedStagedRepositoryBinding)
        assert binding.repository == "owner/repository"
        assert binding.base_branch == "main"
        assert binding.base_sha == "a" * 40
        assert binding.github_integration_id == team_integration.id
        assert binding.github_user_integration_id == personal.id
        assert binding.github_installation_id == "installation-1"
        assert len(binding.grant_version) == 64
        mock_get.assert_any_call("/repos/owner/repository", endpoint="/repos/{owner}/{repo}")
        mock_get.assert_any_call(
            "/repos/owner/repository/branches/main", endpoint="/repos/{owner}/{repo}/branches/{branch}"
        )

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_resolution_uses_the_live_base_not_a_rewritten_cached_sha(self, mock_get: MagicMock) -> None:
        self._create_personal_integration()
        self._create_team_integration(
            self.team,
            repositories=[{**self._repository(), "default_branch": "main", "default_branch_sha": "b" * 40}],
        )
        mock_get.side_effect = [
            {
                "full_name": "owner/repository",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
            },
            {"commit": {"sha": "c" * 40}},
        ]

        binding = self._resolve()

        assert binding is not None
        assert binding.base_sha == "c" * 40

    def test_fails_closed_for_cross_team_or_non_member_actor(self) -> None:
        self._create_personal_integration()
        self._create_team_integration(self.other_team)

        assert list_authorizable_repositories(team_id=self.team.id, actor_id=self.user.id) == ()
        assert self._resolve() is None

        self._create_team_integration(self.team)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        assert list_authorizable_repositories(team_id=self.team.id, actor_id=self.user.id) == ()
        assert self._resolve() is None

    def test_fails_closed_for_stale_token_read_only_or_missing_cache(self) -> None:
        self._create_personal_integration(usable=False)
        self._create_team_integration(self.team)
        assert self._resolve() is None

        UserIntegration.objects.filter(user=self.user).delete()
        personal = self._create_personal_integration()
        personal.config["user_access_token_expires_at"] = int(time.time()) - 1
        personal.save(update_fields=["config", "updated_at"])
        assert self._resolve() is None

        UserIntegration.objects.filter(user=self.user).delete()
        self._create_personal_integration(repositories=[self._repository(can_push=False)])
        assert self._resolve() is None

        UserIntegration.objects.filter(user=self.user).delete()
        self._create_personal_integration(repositories=[])
        assert self._resolve() is None

        UserIntegration.objects.filter(user=self.user).delete()
        self._create_personal_integration()
        Integration.objects.filter(team=self.team).update(repository_cache={})
        assert self._resolve() is None

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_grant_version_changes_when_an_exact_cache_version_changes(self, mock_get: MagicMock) -> None:
        personal = self._create_personal_integration()
        self._create_team_integration(self.team)
        mock_get.side_effect = [
            {
                "full_name": "owner/repository",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
            },
            {"commit": {"sha": "e" * 40}},
            {
                "full_name": "owner/repository",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
            },
            {"commit": {"sha": "e" * 40}},
        ]

        first = self._resolve()
        personal.repository_cache_updated_at = timezone.now()
        personal.save(update_fields=["repository_cache_updated_at", "updated_at"])
        second = self._resolve()

        assert first is not None
        assert second is not None
        assert first.grant_version != second.grant_version

    def test_fails_closed_for_ambiguous_integrations_unless_the_team_integration_is_selected(self) -> None:
        self._create_personal_integration(installation_id="installation-1")
        self._create_personal_integration(installation_id="installation-2")
        first = self._create_team_integration(self.team, installation_id="installation-1")
        self._create_team_integration(self.team, installation_id="installation-2")

        assert self._resolve() is None

        with patch.object(
            GitHubIntegration,
            "_gh_api_get",
            side_effect=[
                {
                    "full_name": "owner/repository",
                    "private": True,
                    "visibility": "private",
                    "default_branch": "main",
                },
                {"commit": {"sha": "d" * 40}},
            ],
        ):
            binding = self._resolve(github_integration_id=first.id)

        assert binding is not None
        assert binding.github_integration_id == first.id
        assert binding.github_user_integration_id == UserIntegration.objects.get(integration_id="installation-1").id

    @override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=())
    def test_allows_private_and_denies_public_repositories_by_default(self) -> None:
        private = self._repository("owner/private")
        public = self._repository("owner/public", private=False)
        self._create_personal_integration(repositories=[private, public])
        self._create_team_integration(self.team, repositories=[private, public])

        assert [
            entry.repository for entry in list_authorizable_repositories(team_id=self.team.id, actor_id=self.user.id)
        ] == ["owner/private"]

    @override_settings(PULSE_PUBLIC_REPOSITORY_ALLOWLIST=("OWNER/PUBLIC",))
    def test_allows_explicitly_allowlisted_public_repositories(self) -> None:
        public = self._repository("owner/public", private=False)
        self._create_personal_integration(repositories=[public])
        self._create_team_integration(self.team, repositories=[public])

        assert [
            entry.repository for entry in list_authorizable_repositories(team_id=self.team.id, actor_id=self.user.id)
        ] == ["owner/public"]

        with patch.object(
            GitHubIntegration,
            "_gh_api_get",
            side_effect=[
                {
                    "full_name": "owner/public",
                    "private": False,
                    "visibility": "public",
                    "default_branch": "main",
                },
                {"commit": {"sha": "b" * 40}},
            ],
        ):
            binding = self._resolve(repository="owner/public")

        assert binding is not None
        assert binding.repository == "owner/public"

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_fails_closed_for_malformed_repository_or_live_base_response(self, mock_get: MagicMock) -> None:
        self._create_personal_integration()
        self._create_team_integration(self.team)

        assert self._resolve(repository="owner/repository/extra") is None
        assert self._resolve(repository="owner/../repository") is None
        assert self._resolve(repository=" owner/repository") is None

        mock_get.side_effect = [
            {
                "full_name": "owner/repository",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
            },
            {"commit": {"sha": "not-a-sha"}},
        ]
        assert self._resolve() is None

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_fails_closed_when_a_cached_private_repository_is_live_public(self, mock_get: MagicMock) -> None:
        self._create_personal_integration()
        self._create_team_integration(self.team)
        mock_get.return_value = {
            "full_name": "owner/repository",
            "private": False,
            "visibility": "public",
            "default_branch": "main",
        }

        assert self._resolve() is None
        mock_get.assert_called_once_with("/repos/owner/repository", endpoint="/repos/{owner}/{repo}")

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_fails_closed_when_live_repository_name_differs_from_the_cached_binding(self, mock_get: MagicMock) -> None:
        self._create_personal_integration()
        self._create_team_integration(self.team)
        mock_get.return_value = {
            "full_name": "owner/renamed-repository",
            "private": True,
            "visibility": "private",
            "default_branch": "main",
        }

        assert self._resolve() is None
        mock_get.assert_called_once_with("/repos/owner/repository", endpoint="/repos/{owner}/{repo}")

    @patch.object(GitHubIntegration, "_gh_api_get")
    def test_fails_closed_when_the_selected_installation_changes_during_live_lookup(self, mock_get: MagicMock) -> None:
        personal = self._create_personal_integration()
        team_integration = self._create_team_integration(self.team)

        calls = 0

        def live_response(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                UserIntegration.objects.filter(id=personal.id).update(integration_id="installation-2")
                Integration.objects.filter(id=team_integration.id).update(integration_id="installation-2")
                return {
                    "full_name": "owner/repository",
                    "private": True,
                    "visibility": "private",
                    "default_branch": "main",
                }
            if calls == 2:
                return {"commit": {"sha": "f" * 40}}
            raise AssertionError("Unexpected GitHub call")

        mock_get.side_effect = live_response

        assert self._resolve() is None
        personal.refresh_from_db()
        team_integration.refresh_from_db()
        assert personal.integration_id == "installation-2"
        assert team_integration.integration_id == "installation-2"
        mock_get.assert_has_calls(
            [
                call("/repos/owner/repository", endpoint="/repos/{owner}/{repo}"),
                call("/repos/owner/repository/branches/main", endpoint="/repos/{owner}/{repo}/branches/{branch}"),
            ]
        )
        assert mock_get.call_count == 2

    def test_dtos_do_not_expose_credentials(self) -> None:
        assert set(AuthorizableRepository.__dataclass_fields__) == {
            "repository",
            "github_integration_id",
            "github_user_integration_id",
            "github_installation_id",
        }
        assert set(ResolvedStagedRepositoryBinding.__dataclass_fields__) == {
            "repository",
            "base_sha",
            "base_branch",
            "github_integration_id",
            "github_user_integration_id",
            "github_installation_id",
            "grant_version",
        }
        assert get_type_hints(AuthorizableRepository)["github_user_integration_id"] is UUID
