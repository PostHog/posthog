import smtplib
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.test.authentication_checks import covers_authentication

from products.messaging.backend.presentation.views.message_templates import SmtpTestRequestSerializer
from products.messaging.backend.presentation.views.smtp_activity import (
    SMTP_RELAY_ACTIVITY_PURPOSE,
    SmtpRelayActivityJWTAuthentication,
)
from products.messaging.backend.services.smtp_activity import SMTP_ACTIVITY_LIMIT, recent_smtp_activity

SMTP_FLAGS = ["workflows-smtp-relay", "workflows-email-from-code"]


def _flags_on(*keys: str) -> Any:
    return patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *_args, **_kwargs: flag in keys)


@override_settings(SMTP_RELAY_HOST="smtp.example.com", SMTP_RELAY_CONNECT_PORT=587)
class TestSmtpRelayApi(APIBaseTest):
    def _key_client(self, scopes: list[str], team: Team | None = None) -> APIClient:
        token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team, label=f"smtp {token[:8]}", secure_value=hash_key_value(token), scopes=scopes
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    @parameterized.expand(
        [
            ("can_send", ["transactional_email:write"], SMTP_FLAGS, status.HTTP_200_OK),
            ("legacy_scope", ["hog_flow:write"], SMTP_FLAGS, status.HTTP_200_OK),
            ("read_only_key", ["transactional_email:read"], SMTP_FLAGS, status.HTTP_403_FORBIDDEN),
            ("relay_flag_off", ["transactional_email:write"], ["workflows-email-from-code"], status.HTTP_404_NOT_FOUND),
            ("code_sends_flag_off", ["transactional_email:write"], ["workflows-smtp-relay"], status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_check_says_which_project_a_key_sends_for(
        self, _name: str, scopes: list[str], flags: list[str], expected: int
    ) -> None:
        with _flags_on(*flags):
            response = self._key_client(scopes).post("/api/projects/@current/messaging/send/smtp_check/", {})

        assert response.status_code == expected, response.content
        if expected == status.HTTP_200_OK:
            assert response.json() == {"team_id": self.team.id}

    def test_check_refuses_an_unknown_key(self) -> None:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer phs_notarealkey")

        with _flags_on(*SMTP_FLAGS):
            response = client.post("/api/projects/@current/messaging/send/smtp_check/", {})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @covers_authentication(SmtpRelayActivityJWTAuthentication)
    @override_settings(SMTP_RELAY_ACTIVITY_JWT_SECRETS=["activity-key"])
    def test_activity_is_newest_first_capped_and_kept_per_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {SMTP_RELAY_ACTIVITY_PURPOSE.mint({'team_id': self.team.id})}")

        for index in range(SMTP_ACTIVITY_LIMIT + 2):
            response = client.post(
                f"/api/projects/{self.team.id}/internal/messaging/smtp_activity",
                {"kind": "refused", "reply": f"550 number {index}", "from": "a@example.com", "to": ["b@example.com"]},
                format="json",
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
        with _flags_on(*SMTP_FLAGS):
            self.client.force_login(self.user)
            activity = self.client.get(f"/api/projects/{self.team.id}/messaging/smtp/setup/").json()["activity"]
            other = self.client.get(f"/api/projects/{other_team.id}/messaging/smtp/setup/").json()["activity"]

        assert len(activity) == SMTP_ACTIVITY_LIMIT
        assert activity[0]["reply"] == f"550 number {SMTP_ACTIVITY_LIMIT + 1}"
        assert activity[0]["from"] == "a@example.com"
        assert other == []

    @override_settings(SMTP_RELAY_ACTIVITY_JWT_SECRETS=["activity-key"])
    def test_activity_only_takes_the_relays_token_for_the_same_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        url = f"/api/projects/{self.team.id}/internal/messaging/smtp_activity"
        body = {"kind": "refused", "reply": "550 made up"}
        other_team_token = APIClient()
        other_team_token.credentials(
            HTTP_AUTHORIZATION=f"Bearer {SMTP_RELAY_ACTIVITY_PURPOSE.mint({'team_id': other_team.id})}"
        )

        for client in (self._key_client(["transactional_email:write"]), other_team_token):
            response = client.post(url, body, format="json")

            assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), response.content
        assert recent_smtp_activity(self.team.id) == []

    def test_setup_is_hidden_without_the_flag(self) -> None:
        with _flags_on():
            response = self.client.get(f"/api/projects/{self.team.id}/messaging/smtp/setup/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("accepted", None, True, "The relay queued the test email."),
            (
                "bad_key",
                smtplib.SMTPAuthenticationError(535, b"5.7.8 Invalid credentials."),
                False,
                "535 5.7.8 Invalid credentials.",
            ),
            (
                "refused_message",
                smtplib.SMTPDataError(550, b"5.7.1 No verified sender."),
                False,
                "550 5.7.1 No verified sender.",
            ),
            (
                "relay_down",
                ConnectionRefusedError(),
                False,
                "PostHog couldn't reach the SMTP relay. Try again shortly, and contact support if it continues.",
            ),
        ]
    )
    def test_test_send_reports_what_the_relay_answered(
        self, _name: str, error: Exception | None, ok: bool, reply: str
    ) -> None:
        client = MagicMock()
        client.__enter__.return_value = client
        client.send_message.side_effect = error
        with _flags_on(*SMTP_FLAGS), patch("smtplib.SMTP", return_value=client):
            response = self.client.post(
                f"/api/projects/{self.team.id}/messaging/smtp/test/",
                {"password": "phs_key", "from": "a@example.com", "to": "b@example.com"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"ok": ok, "reply": reply}

    def test_test_send_refuses_a_sender_it_could_not_put_in_a_header(self) -> None:
        with _flags_on(*SMTP_FLAGS):
            response = self.client.post(
                f"/api/projects/{self.team.id}/messaging/smtp/test/",
                {"password": "phs_key", "from": "a@example.com\nBcc: c@example.com", "to": "b@example.com"},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["attr"] == "from"


class TestSmtpTestRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("line_break_in_sender", {"from": "a@example.com\r\nBcc: c@example.com"}, "from"),
            ("tab_in_sender", {"from": "a\t<a@example.com>"}, "from"),
            ("non_ascii_key", {"password": "phs_ключ"}, "password"),
        ]
    )
    def test_refuses_input_smtp_can_not_carry(self, _name: str, change: dict[str, str], field: str) -> None:
        serializer = SmtpTestRequestSerializer(
            data={"password": "phs_key", "from": "a@example.com", "to": "b@example.com", **change}
        )

        assert not serializer.is_valid()
        assert list(serializer.errors) == [field]

    def test_keeps_a_display_name_with_non_ascii_letters(self) -> None:
        serializer = SmtpTestRequestSerializer(
            data={"password": "phs_key", "from": "Zoë <a@example.com>", "to": "b@example.com"}
        )

        assert serializer.is_valid(), serializer.errors
