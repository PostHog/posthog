from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.github_integration_base import ReauthorizationRequired
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.user_integration import UserIntegration

from products.access_control.backend.models.access_control import AccessControl
from products.slack_app.backend.models import SlackChannel, SlackChannelSettings, SlackSettings

SLACK_TEAM_ID = "T12345"


class TestSlackAppSettings(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = self._slack_install(self.team)

    def _slack_install(
        self, team: Team, slack_team_id: str = SLACK_TEAM_ID, created_by: User | None = None
    ) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=slack_team_id,
            config={"team": {"id": slack_team_id, "name": "Hedgebox"}},
            sensitive_config={"access_token": "xoxb-test"},
            created_by=created_by,
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/slack_app_settings/{self.integration.id}/{suffix}"

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    def _link_slack_user(self, slack_user_id: str = "U123") -> None:
        UserIntegration.objects.create(
            user=self.user, kind="slack", integration_id=slack_user_id, config={"slack_team_id": SLACK_TEAM_ID}
        )

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, False, status.HTTP_403_FORBIDDEN),
            ("admin", OrganizationMembership.Level.ADMIN, False, status.HTTP_200_OK),
            ("member_who_installed", OrganizationMembership.Level.MEMBER, True, status.HTTP_200_OK),
        ]
    )
    def test_only_admins_and_the_installer_change_workspace_settings(
        self, _name: str, level: OrganizationMembership.Level, installed: bool, expected: int
    ) -> None:
        self._set_level(level)
        if installed:
            self.integration.created_by = self.user
            self.integration.save()

        response = self.client.patch(
            self._url("workspace/"),
            {"reactions": {"working": {"emoji": ":hog-is-watching:"}}, "external_channels_enabled": True},
            format="json",
        )

        assert response.status_code == expected
        row = SlackSettings.objects.filter(slack_workspace_id=SLACK_TEAM_ID, slack_user_id__isnull=True).first()
        if expected == status.HTTP_200_OK:
            assert row is not None
            assert row.reactions == {"working": {"emoji": "hog-is-watching"}}
            assert row.external_channels_enabled is True
            assert response.json()["can_edit_workspace"] is True
        else:
            assert row is None

    @parameterized.expand([("no_approved_channel", False), ("approved_channel", True)])
    def test_external_channels_follow_existing_approvals_until_an_admin_picks(
        self, _name: str, has_approval: bool
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        if has_approval:
            SlackChannel.objects.create(
                slack_workspace_id=SLACK_TEAM_ID, slack_channel_id="C999", approved_at=timezone.now()
            )

        assert self.client.get(self._url()).json()["workspace"]["external_channels_enabled"] is has_approval

        self.client.patch(self._url("workspace/"), {"external_channels_enabled": False}, format="json")

        assert self.client.get(self._url()).json()["workspace"]["external_channels_enabled"] is False

    def test_personal_reactions_need_a_linked_slack_account(self) -> None:
        response = self.client.patch(self._url("personal/"), {"reactions": {"done": {"enabled": True}}}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not SlackSettings.objects.exists()

    def test_personal_reactions_override_the_workspace_for_this_person_only(self) -> None:
        self._link_slack_user()
        SlackSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID,
            slack_user_id=None,
            reactions={"working": {"emoji": "hog-ws"}, "done": {"emoji": "hog-done", "enabled": True}},
        )

        response = self.client.patch(
            self._url("personal/"), {"reactions": {"working": {"emoji": "rocket"}}}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        personal = response.json()["personal"]
        assert personal["slack_user_id"] == "U123"
        assert personal["effective_reactions"]["working"] == {"emoji": "rocket", "enabled": True}
        assert personal["effective_reactions"]["done"] == {"emoji": "hog-done", "enabled": True}
        assert SlackSettings.objects.get(slack_workspace_id=SLACK_TEAM_ID, slack_user_id="U123").reactions == {
            "working": {"emoji": "rocket"}
        }

    def test_personal_settings_round_trip_and_a_cleared_project_falls_back(self) -> None:
        self._link_slack_user()

        response = self.client.patch(
            self._url("personal/"),
            {
                "default_integration_id": self.integration.id,
                "untagged_followup_mode": "never",
                "thread_join_mode": "ask_per_person",
                "feature_tips_enabled": False,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        personal = response.json()["personal"]
        assert personal["default_integration_id"] == self.integration.id
        assert personal["untagged_followup_mode"] == "never"
        assert personal["untagged_question_mode"] == "ask"
        assert personal["thread_join_mode"] == "ask_per_person"
        assert personal["feature_tips_enabled"] is False

        cleared = self.client.patch(self._url("personal/"), {"default_integration_id": None}, format="json")

        assert cleared.json()["personal"]["default_integration_id"] is None
        assert cleared.json()["personal"]["untagged_followup_mode"] == "never"

    def test_personal_project_must_be_one_the_person_can_open(self) -> None:
        self._link_slack_user()
        other_org_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))
        other_install = self._slack_install(other_org_team)

        response = self.client.patch(
            self._url("personal/"), {"default_integration_id": other_install.id}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_emoji_name_is_refused(self) -> None:
        self._link_slack_user()

        response = self.client.patch(
            self._url("personal/"), {"reactions": {"working": {"emoji": "not an emoji"}}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_any_member_changes_their_organizations_channel_settings_only(self) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)
        self.user.first_name = "Jamie"
        self.user.save()
        other_organization = Organization.objects.create(name="Other org")
        other_editor = User.objects.create(email="editor@other.example.com", first_name="")
        SlackChannelSettings.objects.create(
            slack_workspace_id=SLACK_TEAM_ID,
            slack_channel_id="C111",
            organization=other_organization,
            default_repository="other/secret",
            updated_by=other_editor,
        )

        response = self.client.put(
            self._url("channels/C111/"),
            {
                "default_integration_id": self.integration.id,
                "default_repository": "example/web-app",
                "untagged_question_mode": "ask",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["updated_by_name"] == "Jamie"
        channels = self.client.get(self._url("channels/")).json()["channels"]
        assert [(c["default_repository"], c["default_integration_id"]) for c in channels] == [
            ("example/web-app", self.integration.id)
        ]
        assert SlackChannelSettings.objects.get(organization=other_organization).default_repository == "other/secret"

        cleared = self.client.put(
            self._url("channels/C111/"),
            {"default_integration_id": None, "default_repository": None, "untagged_question_mode": None},
            format="json",
        )

        assert cleared.status_code == status.HTTP_200_OK
        assert not SlackChannelSettings.objects.filter(organization=self.organization).exists()

    @parameterized.expand([("connected", True), ("not_connected", False)])
    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_repository_options_come_from_the_persons_own_github(
        self, _name: str, connected: bool, mock_github_class
    ) -> None:
        cache.clear()
        if connected:
            UserIntegration.objects.create(
                user=self.user,
                kind=UserIntegration.IntegrationKind.GITHUB,
                integration_id="gh-1",
                config={},
                sensitive_config={"access_token": "gh-token"},
            )
        mock_github_class.return_value.list_all_cached_repositories.return_value = [
            {"full_name": "hedgebox/web"},
            {"full_name": "Hedgebox/api"},
        ]

        response = self.client.get(self._url("repositories/"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "repositories": ["Hedgebox/api", "hedgebox/web"] if connected else [],
            "github_connected": connected,
        }

    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_repository_options_ask_to_reconnect_an_expired_github(self, mock_github_class) -> None:
        cache.clear()
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-1",
            config={},
            sensitive_config={"access_token": "gh-token"},
        )
        mock_github_class.return_value.list_all_cached_repositories.side_effect = ReauthorizationRequired()

        response = self.client.get(self._url("repositories/"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Reconnect GitHub" in response.json()["detail"]

    @parameterized.expand(
        [("project_scope_only", ["integration:read"], 403), ("with_user_scope", ["integration:read", "user:read"], 200)]
    )
    def test_repository_options_need_the_user_scope(self, _name: str, scopes: list[str], expected: int) -> None:
        cache.clear()
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response = self.client.get(self._url("repositories/"), HTTP_AUTHORIZATION=f"Bearer {key}")

        assert response.status_code == expected

    @parameterized.expand(
        [
            ("project_in_another_workspace", "other_workspace", None, "C111", None),
            ("project_of_another_organization", "other_organization", None, "C111", None),
            ("repository_not_owner_slash_name", None, "web-app", "C111", None),
            ("not_a_channel_id", None, None, "general", None),
            ("channel_cannot_answer_automatically", None, None, "C111", "auto"),
        ]
    )
    def test_channel_settings_refuse_bad_values(
        self, _name: str, project: str | None, repository: str | None, channel_id: str, mode: str | None
    ) -> None:
        other_team = Team.objects.create(organization=self.organization)
        projects = {"other_workspace": self._slack_install(other_team, "T999")}
        if project == "other_organization":
            other_organization = Organization.objects.create(name="Other org")
            OrganizationMembership.objects.create(user=self.user, organization=other_organization)
            projects["other_organization"] = self._slack_install(Team.objects.create(organization=other_organization))

        response = self.client.put(
            self._url(f"channels/{channel_id}/"),
            {
                "default_integration_id": projects[project].id if project else None,
                "default_repository": repository,
                "untagged_question_mode": mode,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SlackChannelSettings.objects.exists()

    @patch(
        "products.access_control.backend.facade.user_access_control.UserAccessControl.access_controls_supported", True
    )
    def test_a_member_restricted_on_the_install_cannot_read_or_change_its_settings(self) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)
        AccessControl.objects.create(
            team=self.team, resource="integration", resource_id=str(self.integration.id), access_level="none"
        )

        read = self.client.get(self._url())
        write = self.client.put(
            self._url("channels/C111/"),
            {"default_integration_id": None, "default_repository": "example/web-app", "untagged_question_mode": None},
            format="json",
        )

        assert read.status_code == status.HTTP_403_FORBIDDEN
        assert write.status_code == status.HTTP_403_FORBIDDEN
        assert not SlackChannelSettings.objects.exists()
