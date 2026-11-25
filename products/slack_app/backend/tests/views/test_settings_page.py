from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership, User
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.models import SlackChannel, SlackSettings

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

    def test_invalid_emoji_name_is_refused(self) -> None:
        self._link_slack_user()

        response = self.client.patch(
            self._url("personal/"), {"reactions": {"working": {"emoji": "not an emoji"}}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_any_member_changes_channel_settings_and_approval_rows_stay_hidden(self) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)
        self.user.first_name = "Jamie"
        self.user.save()
        SlackChannel.objects.create(
            slack_workspace_id=SLACK_TEAM_ID, slack_channel_id="C999", approved_at=timezone.now()
        )
        SlackChannel.objects.create(
            slack_workspace_id=SLACK_TEAM_ID, slack_channel_id="C111", approved_at=timezone.now()
        )

        response = self.client.put(
            self._url("channels/C111/"),
            {
                "default_integration_id": self.integration.id,
                "default_repository": "example/web-app",
                "untagged_question_mode": "auto",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["updated_by_name"] == "Jamie"
        channels = self.client.get(self._url("channels/")).json()["channels"]
        assert [c["slack_channel_id"] for c in channels] == ["C111"]
        assert channels[0]["default_integration_id"] == self.integration.id
        assert SlackChannel.objects.get(slack_channel_id="C111").approved_at is not None

    @parameterized.expand(
        [
            ("project_in_another_workspace", "other_workspace", None, "C111"),
            ("repository_not_owner_slash_name", None, "web-app", "C111"),
            ("not_a_channel_id", None, None, "general"),
        ]
    )
    def test_channel_settings_refuse_bad_values(
        self, _name: str, project: str | None, repository: str | None, channel_id: str
    ) -> None:
        other_integration = self._slack_install(Team.objects.create(organization=self.organization), "T999")

        response = self.client.put(
            self._url(f"channels/{channel_id}/"),
            {
                "default_integration_id": other_integration.id if project else None,
                "default_repository": repository,
                "untagged_question_mode": None,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SlackChannel.objects.exists()
