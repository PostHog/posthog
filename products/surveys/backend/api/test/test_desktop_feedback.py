import io
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from PIL import Image
from rest_framework import status

from posthog.models import Team, UploadedMedia
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization
from posthog.ph_client import PH_US_API_KEY


def _image_file(name: str = "example.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestDesktopFeedback(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        internal_org = Organization.objects.create(name="PostHog internal")
        self.internal_team = Team.objects.create(
            organization=internal_org,
            name="Internal feedback",
            api_token=PH_US_API_KEY,
        )

    @patch("posthog.models.uploaded_media.object_storage.write")
    @patch("products.surveys.backend.desktop_feedback.get_client")
    def test_submits_response_and_stores_media_outside_the_selected_project(self, get_client, _write_object) -> None:
        client = MagicMock()
        client.capture.return_value = "00000000-0000-0000-0000-000000000001"
        get_client.return_value = client

        response = self.client.post(
            "/api/desktop_feedback/",
            {
                "response": "The page did not load",
                "source": "Generic (Leave feedback button)",
                "feedback_view": "task-detail",
                "feedback_task_id": "task-123",
                "feedback_app_logs": "[info] Example log",
                "app_version": "1.2.3",
                "session_id": "00000000-0000-0000-0000-000000000002",
                "screenshot": _image_file("screenshot.png"),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json() == {
            "accepted": True,
            "response_id": "00000000-0000-0000-0000-000000000001",
        }
        media = UploadedMedia.objects.get()
        assert media.team_id == self.internal_team.id
        assert media.team_id != self.team.id
        properties = client.capture.call_args.kwargs["properties"]
        assert properties["$survey_id"] == "019ee235-2e3b-0000-64b3-5f2efa487452"
        assert properties["$survey_response_68648b23-caaf-4080-ae5f-051513d3097f"] == "The page did not load"
        assert properties["feedback_screenshot_url"].endswith(f"/uploaded_media/{media.id}")
        assert properties["feedback_app_logs"] == "[info] Example log"
        assert properties["$session_id"] == "00000000-0000-0000-0000-000000000002"

    @patch("products.surveys.backend.desktop_feedback.get_client")
    def test_accepts_desktop_oauth_token(self, get_client) -> None:
        client = MagicMock()
        client.capture.return_value = "00000000-0000-0000-0000-000000000001"
        get_client.return_value = client
        oauth_app = OAuthApplication.objects.create(
            name="PostHog Desktop test",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_app,
            token="pha_desktop_feedback_test",
            expires=timezone.now() + timedelta(hours=1),
            scope="survey:write",
        )
        self.client.logout()

        response = self.client.post(
            "/api/desktop_feedback/",
            {
                "response": "The page did not load",
                "source": "Generic (Leave feedback button)",
                "feedback_view": "task-detail",
            },
            format="multipart",
            headers={"authorization": f"Bearer {access_token.token}"},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    @patch("products.surveys.backend.desktop_feedback.object_storage.delete")
    @patch("posthog.models.uploaded_media.object_storage.write")
    @patch("products.surveys.backend.desktop_feedback.get_client")
    def test_capture_failure_removes_uploaded_media(self, get_client, _write_object, delete_object) -> None:
        client = MagicMock()
        client.capture.side_effect = RuntimeError("capture unavailable")
        get_client.return_value = client

        response = self.client.post(
            "/api/desktop_feedback/",
            {
                "response": "The page did not load",
                "source": "Generic (Leave feedback button)",
                "feedback_view": "task-detail",
                "screenshot": _image_file(),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert not UploadedMedia.objects.exists()
        delete_object.assert_called_once()
