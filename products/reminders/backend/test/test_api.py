from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.reminders.backend.models import Reminder


class TestReminderAPI(APIBaseTest):
    def _authenticate_with_oauth(
        self,
        scopes: str,
        scoped_teams: list[int] | None = None,
        scoped_organizations: list[str] | None = None,
    ) -> None:
        application = OAuthApplication.objects.create(
            name="Reminders MCP",
            client_id="reminders-test-client",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_reminders_test",
            scope=scopes,
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=scoped_teams if scoped_teams is not None else [self.team.id],
            scoped_organizations=scoped_organizations or [],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def _authenticate_with_personal_api_key(self, scopes: list[str]) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="reminders",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {value}")

    @parameterized.expand(
        [
            ("oauth_token",),
            ("personal_api_key",),
            ("session",),
        ]
    )
    def test_list_reminders_accepts_every_supported_credential(self, credential: str) -> None:
        fire_at = timezone.now() + timedelta(days=1)
        Reminder.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            title="Check the funnel",
            scheduled_at=fire_at,
            next_fire_at=fire_at,
        )
        if credential == "oauth_token":
            self._authenticate_with_oauth("user:read")
        elif credential == "personal_api_key":
            self._authenticate_with_personal_api_key(["user:read"])

        response = self.client.get("/api/reminders/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_create_reminder_with_oauth_token(self) -> None:
        self._authenticate_with_oauth("user:read user:write")

        response = self.client.post(
            "/api/reminders/",
            {
                "organization": str(self.organization.id),
                "team": self.team.id,
                "title": "Review the weekly numbers",
                "recurrence_interval": "weekly",
                "timezone": "UTC",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Reminder.objects.filter(created_by=self.user).count(), 1)

    def test_create_reminder_is_rejected_without_the_write_scope(self) -> None:
        self._authenticate_with_oauth("user:read")

        response = self.client.post(
            "/api/reminders/",
            {
                "organization": str(self.organization.id),
                "title": "Review the weekly numbers",
                "recurrence_interval": "weekly",
            },
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(Reminder.objects.count(), 0)

    @parameterized.expand(
        [
            ("scoped_to_another_project",),
            ("scoped_to_another_organization",),
        ]
    )
    def test_create_reminder_rejects_a_target_outside_the_credential_reach(self, restriction: str) -> None:
        other_organization, _, other_team = Organization.objects.bootstrap(self.user)
        if restriction == "scoped_to_another_project":
            self._authenticate_with_oauth("user:write", scoped_teams=[other_team.id])
        else:
            self._authenticate_with_oauth("user:write", scoped_organizations=[str(other_organization.id)])

        response = self.client.post(
            "/api/reminders/",
            {
                "organization": str(self.organization.id),
                "team": self.team.id,
                "title": "Review the weekly numbers",
                "recurrence_interval": "weekly",
            },
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(Reminder.objects.count(), 0)

    def test_list_reminders_hides_a_project_outside_the_credential_reach(self) -> None:
        _, _, other_team = Organization.objects.bootstrap(self.user)
        fire_at = timezone.now() + timedelta(days=1)
        for team in (self.team, other_team):
            Reminder.objects.create(
                organization=team.organization,
                team=team,
                created_by=self.user,
                title="Check the funnel",
                scheduled_at=fire_at,
                next_fire_at=fire_at,
            )
        self._authenticate_with_oauth("user:read", scoped_teams=[self.team.id])

        response = self.client.get("/api/reminders/")

        self.assertEqual(response.status_code, 200, response.content)
        returned_teams = [result["team"] for result in response.json()["results"]]
        self.assertEqual(returned_teams, [self.team.id])
