from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.messaging.backend.services.smtp_activity import SMTP_ACTIVITY_LIMIT, recent_smtp_activity

SMTP_FLAGS = ["workflows-smtp-relay", "workflows-email-from-code"]


def _flags_on(*keys: str) -> Any:
    return patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *_args, **_kwargs: flag in keys)


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

    def test_activity_is_newest_first_capped_and_kept_per_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        url = f"/api/projects/{self.team.id}/messaging/send/smtp_activity/"
        client = self._key_client(["transactional_email:write"])

        with _flags_on(*SMTP_FLAGS):
            for index in range(SMTP_ACTIVITY_LIMIT + 2):
                response = client.post(
                    url,
                    {
                        "kind": "refused",
                        "reply": f"550 number {index}",
                        "from": "a@example.com",
                        "to": ["b@example.com"],
                    },
                    format="json",
                )
                assert response.status_code == status.HTTP_204_NO_CONTENT, response.content

        activity = recent_smtp_activity(self.team.id)
        other = recent_smtp_activity(other_team.id)
        assert len(activity) == SMTP_ACTIVITY_LIMIT
        assert activity[0]["reply"] == f"550 number {SMTP_ACTIVITY_LIMIT + 1}"
        assert activity[0]["from"] == "a@example.com"
        assert other == []
