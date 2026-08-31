from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.subscriptions.backend.pulse.repository_grants import repository_grant_authorization_is_live


class TestRepositoryGrantAuthorization(SimpleTestCase):
    def test_requires_the_same_active_owner_and_exact_repository_binding(self) -> None:
        grant = MagicMock(
            authorizer_id=4,
            automation_owner_id=4,
            repository="PostHog/posthog",
            integration_id=5,
            repository_installation_id="installation-5",
        )
        authorization = MagicMock(
            repository="posthog/POSTHOG",
            github_integration_id=5,
            github_installation_id="installation-5",
        )
        with (
            patch("products.subscriptions.backend.pulse.repository_grants.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.repository_grants.tasks_api.resolve_repository_authorization",
                return_value=authorization,
            ) as resolve,
        ):
            users.return_value.exists.return_value = True
            assert repository_grant_authorization_is_live(team_id=1, grant=grant)

        resolve.assert_called_once_with(
            team_id=1,
            user_id=4,
            repository="PostHog/posthog",
            github_integration_id=5,
        )

    def test_rejects_mismatched_owner_without_resolving_authority(self) -> None:
        grant = MagicMock(authorizer_id=3, automation_owner_id=4)
        with patch(
            "products.subscriptions.backend.pulse.repository_grants.tasks_api.resolve_repository_authorization"
        ) as resolve:
            assert not repository_grant_authorization_is_live(team_id=1, grant=grant)
        resolve.assert_not_called()

    def test_rejects_inactive_owner(self) -> None:
        grant = MagicMock(authorizer_id=4, automation_owner_id=4)
        with (
            patch("products.subscriptions.backend.pulse.repository_grants.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.repository_grants.tasks_api.resolve_repository_authorization"
            ) as resolve,
        ):
            users.return_value.exists.return_value = False
            assert not repository_grant_authorization_is_live(team_id=1, grant=grant)
        resolve.assert_not_called()

    def test_rejects_changed_installation_binding(self) -> None:
        grant = MagicMock(
            authorizer_id=4,
            automation_owner_id=4,
            repository="posthog/posthog",
            integration_id=5,
            repository_installation_id="installation-5",
        )
        authorization = MagicMock(
            repository="posthog/posthog",
            github_integration_id=5,
            github_installation_id="installation-6",
        )
        with (
            patch("products.subscriptions.backend.pulse.repository_grants.User.objects.filter") as users,
            patch(
                "products.subscriptions.backend.pulse.repository_grants.tasks_api.resolve_repository_authorization",
                return_value=authorization,
            ),
        ):
            users.return_value.exists.return_value = True
            assert not repository_grant_authorization_is_live(team_id=1, grant=grant)
