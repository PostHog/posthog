import base64
from urllib.error import URLError

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.hog_flow_slack_preview import SharePreviewToSlackRequestSerializer

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-data"
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode()


class TestHogFlowSlackPreview(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flow = HogFlow.objects.create(
            team=self.team,
            name="Onboarding drip",
            status="draft",
            trigger={"type": "event"},
            edges=[],
            actions=[],
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"scope": "chat:write,files:write"},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _share(self, **overrides: object):
        body = {
            "integration_id": self.integration.id,
            "channel": "C0PREVIEW|#workflow-previews",
            "note": "Feedback welcome <!channel>",
            "outline": ["Trigger: Event `signed up`", "Send email: <b>Welcome</b>"],
            "emails": [{"title": "Welcome to PostHog", "image_base64": PNG_BASE64}],
            **overrides,
        }
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{self.flow.id}/share_preview_to_slack/", body, format="json"
        )

    @parameterized.expand(
        [
            ("picked_channel", {}, "C0PREVIEW", None),
            (
                "pasted_thread_link",
                {"channel": None, "thread_link": "https://acme.slack.com/archives/C0THREAD/p1760000000123456"},
                "C0THREAD",
                "1760000000.123456",
            ),
            (
                "pasted_reply_link",
                {
                    "channel": None,
                    "thread_link": "https://acme.slack.com/archives/C0THREAD/p1760000999000001?thread_ts=1760000000.123456&cid=C0THREAD",
                },
                "C0THREAD",
                "1760000000.123456",
            ),
        ]
    )
    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_posts_preview_with_email_images_to_destination(
        self,
        _name: str,
        overrides: dict,
        expected_channel: str,
        expected_thread_ts: str | None,
        mock_slack: MagicMock,
    ) -> None:
        slack_client = mock_slack.return_value
        slack_client.conversations_info.return_value = {"channel": {"id": expected_channel, "is_private": False}}

        response = self._share(**overrides)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"channel": expected_channel, "thread_ts": expected_thread_ts}
        upload = slack_client.files_upload_v2.call_args.kwargs
        assert upload["channel"] == expected_channel
        assert upload.get("thread_ts") == expected_thread_ts
        assert upload["file_uploads"] == [
            {"content": PNG_BYTES, "filename": "email-1.png", "title": "Welcome to PostHog"}
        ]
        message = upload["initial_comment"]
        assert "*Onboarding drip*" in message
        assert f"/project/{self.team.id}/workflows/{self.flow.id}" in message
        assert "Feedback welcome &lt;!channel&gt;" in message
        assert "Send email: &lt;b&gt;Welcome&lt;/b&gt;" in message
        assert "<!channel>" not in message

    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_uploads_jpeg_previews_with_a_jpg_name(self, mock_slack: MagicMock) -> None:
        slack_client = mock_slack.return_value
        slack_client.conversations_info.return_value = {"channel": {"id": "C0PREVIEW", "is_private": False}}
        jpeg = b"\xff\xd8\xff\xe0" + b"fake-jpeg-data"

        response = self._share(emails=[{"title": "Photo email", "image_base64": base64.b64encode(jpeg).decode()}])

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert slack_client.files_upload_v2.call_args.kwargs["file_uploads"] == [
            {"content": jpeg, "filename": "email-1.jpg", "title": "Photo email"}
        ]

    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_posts_text_only_when_workflow_has_no_emails(self, mock_slack: MagicMock) -> None:
        slack_client = mock_slack.return_value
        slack_client.conversations_info.return_value = {"channel": {"id": "C0PREVIEW", "is_private": False}}

        response = self._share(emails=[])

        assert response.status_code == status.HTTP_200_OK, response.json()
        slack_client.files_upload_v2.assert_not_called()
        assert "*Onboarding drip*" in slack_client.chat_postMessage.call_args.kwargs["text"]

    @parameterized.expand(
        [
            ("private_channel_of_someone_else", {"is_private": True}, "private channel"),
            ("direct_message", {"is_im": True}, "direct message"),
        ]
    )
    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_rejects_destinations_the_sharer_may_not_post_to(
        self, _name: str, channel_flags: dict, expected_detail: str, mock_slack: MagicMock
    ) -> None:
        slack_client = mock_slack.return_value
        slack_client.conversations_info.return_value = {"channel": {"id": "C0PREVIEW", **channel_flags}}

        response = self._share()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_detail in response.json()["detail"]
        slack_client.files_upload_v2.assert_not_called()

    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_asks_to_reconnect_when_slack_install_cannot_upload_files(self, mock_slack: MagicMock) -> None:
        self.integration.config = {"scope": "chat:write"}
        self.integration.save()

        response = self._share()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Reconnect Slack" in response.json()["detail"]
        mock_slack.return_value.files_upload_v2.assert_not_called()

    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_rejects_slack_integration_of_another_project(self, mock_slack: MagicMock) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        foreign = Integration.objects.create(
            team=other_team, kind="slack", integration_id="T999", sensitive_config={"access_token": "xoxb-other"}
        )

        response = self._share(integration_id=foreign.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_slack.assert_not_called()

    @parameterized.expand(
        [
            ("app_not_in_channel", SlackApiError("failed", response={"error": "not_in_channel"}), "/invite @PostHog"),
            ("other_slack_error", SlackApiError("failed", response={"error": "invalid_blocks"}), "invalid_blocks"),
            ("upload_transport_error", URLError("connection reset"), "Couldn't reach Slack"),
        ]
    )
    @patch.object(SlackIntegration, "client", new_callable=PropertyMock)
    def test_surfaces_slack_failures_as_bad_request(
        self, _name: str, error: Exception, expected_detail: str, mock_slack: MagicMock
    ) -> None:
        slack_client = mock_slack.return_value
        slack_client.conversations_info.return_value = {"channel": {"id": "C0PREVIEW", "is_private": False}}
        slack_client.files_upload_v2.side_effect = error

        response = self._share()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_detail in response.json()["detail"]


class TestSharePreviewToSlackRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_destination", {"channel": None}, "non_field_errors"),
            (
                "unparseable_thread_link",
                {"channel": None, "thread_link": "https://example.com/not-slack"},
                "thread_link",
            ),
            (
                "image_is_not_png",
                {"emails": [{"title": "Hi", "image_base64": base64.b64encode(b"GIF89a").decode()}]},
                "emails",
            ),
            ("image_is_not_base64", {"emails": [{"title": "Hi", "image_base64": "%%%"}]}, "emails"),
            ("too_many_emails", {"emails": [{"title": "Hi", "image_base64": PNG_BASE64}] * 11}, "emails"),
            (
                "image_over_one_megabyte",
                {
                    "emails": [
                        {"title": "Hi", "image_base64": base64.b64encode(PNG_BYTES + b"0" * 1024 * 1024).decode()}
                    ]
                },
                "emails",
            ),
            (
                "lookalike_host",
                {"channel": None, "thread_link": "https://evilslack.com/archives/C0X/p1760000000123456"},
                "thread_link",
            ),
            (
                "plain_http_link",
                {"channel": None, "thread_link": "http://acme.slack.com/archives/C0X/p1760000000123456"},
                "thread_link",
            ),
            (
                "malformed_thread_ts",
                {"channel": None, "thread_link": "https://acme.slack.com/archives/C0X/p1760000000123456?thread_ts=abc"},
                "thread_link",
            ),
        ]
    )
    def test_rejects_invalid_request(self, _name: str, overrides: dict, error_field: str) -> None:
        serializer = SharePreviewToSlackRequestSerializer(
            data={
                "integration_id": 1,
                "channel": "C0PREVIEW|#workflow-previews",
                "outline": [],
                "emails": [],
                **overrides,
            }
        )

        assert not serializer.is_valid()
        assert error_field in serializer.errors
