from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.workflows.backend.facade.api import set_default_email_sender_if_unset


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalEmailSend(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.template = MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content={"email": {"subject": "Reset your password", "html": "<a href='{{ variables.link }}'>Reset</a>"}},
            type="email",
        )
        self.sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, self.sender.id)
        self.url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/send/"
        self.body = {
            "to": "user@example.com",
            "identifiers": {"distinct_id": "user-1"},
            "message_data": {"link": "https://example.com/reset", "nickname": None},
        }

    def _cdp_accepts(self, mock_post: MagicMock, invocation_id: str = "invocation-1") -> None:
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": invocation_id})

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="transactional email",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def test_queues_the_template_with_the_default_sender_and_message_data(self, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)

        response = self._psak_client(["hog_flow:write"]).post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json() == {"message_id": "invocation-1", "replayed": False}
        url = mock_post.call_args.args[0]
        payload = mock_post.call_args.kwargs["json"]
        assert url.endswith(f"/api/projects/{self.team.id}/messaging/transactional_email")
        assert payload["template_id"] == str(self.template.id)
        assert payload["distinct_id"] == "user-1"
        assert payload["variables"] == {"link": "https://example.com/reset", "nickname": None}
        assert payload["email"]["to"] == {"email": "user@example.com", "name": ""}
        assert payload["email"]["from"] == {"integrationId": self.sender.id}
        assert payload["email"]["subject"] == "Reset your password"
        assert payload["email"]["html"] == "<a href='{{ variables.link }}'>Reset</a>"

    @parameterized.expand(
        [
            ("send_with_write_scope", "post", "send/", ["hog_flow:write"], status.HTTP_202_ACCEPTED),
            ("send_with_read_scope", "post", "send/", ["hog_flow:read"], status.HTTP_403_FORBIDDEN),
            ("retrieve_is_not_a_psak_action", "get", "", ["hog_flow:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_project_secret_api_key_can_only_send(
        self, mock_post, _flag, _capture, _name, method, suffix, scopes, expected_status
    ):
        self._cdp_accepts(mock_post)
        url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/{suffix}"

        response = getattr(self._psak_client(scopes), method)(
            url, self.body if method == "post" else None, format="json"
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("marketing_template", "marketing_template"),
            ("template_without_subject", "template_not_sendable"),
            ("template_without_body", "template_not_sendable"),
            ("unverified_sender", "sender_unavailable"),
            ("liquid_in_recipient", "invalid_recipient"),
        ]
    )
    def test_rejects_a_send_it_cannot_make(self, mock_post, _flag, _capture, case, expected_code):
        body = dict(self.body)
        if case == "marketing_template":
            category = MessageCategory.objects.create(
                team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
            )
            self.template.message_category = category
            self.template.save()
        elif case == "template_without_subject":
            self.template.content = {"email": {"html": "<p>Hi</p>"}}
            self.template.save()
        elif case == "template_without_body":
            self.template.content = {"email": {"subject": "Hi"}}
            self.template.save()
        elif case == "unverified_sender":
            self.sender.config = {"verified": False}
            self.sender.save()
        elif case == "liquid_in_recipient":
            body["to"] = "{{person.properties.email}}@example.com"

        response = self.client.post(self.url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        assert response.json()["type"] == "invalid_request"
        mock_post.assert_not_called()

    def test_a_retried_request_with_the_same_idempotency_key_sends_once(self, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        headers = {"Idempotency-Key": str(uuid4())}

        first = self.client.post(self.url, self.body, format="json", headers=headers)
        second = self.client.post(self.url, self.body, format="json", headers=headers)

        assert first.json() == {"message_id": "invocation-1", "replayed": False}
        assert second.json() == {"message_id": "invocation-1", "replayed": True}
        assert mock_post.call_count == 1

    def test_a_retry_after_an_unknown_outcome_does_not_send_twice(self, mock_post, _flag, _capture):
        mock_post.side_effect = requests.ReadTimeout()
        headers = {"Idempotency-Key": str(uuid4())}

        first = self.client.post(self.url, self.body, format="json", headers=headers)
        second = self.client.post(self.url, self.body, format="json", headers=headers)

        assert first.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert second.status_code == status.HTTP_409_CONFLICT
        assert mock_post.call_count == 1

    def test_reports_quota_limited_teams(self, mock_post, _flag, _capture):
        mock_post.return_value = MagicMock(status_code=429, json=lambda: {"error": "quota_limited"})

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json()["code"] == "quota_limited"

    def test_is_hidden_while_the_flag_is_off(self, mock_post, flag, _capture):
        flag.return_value = False

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_post.assert_not_called()
