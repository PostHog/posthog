import io
from datetime import timedelta
from urllib.parse import urlsplit

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from PIL import Image
from rest_framework import status

from posthog.models import Team, UploadedMedia
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.uploaded_media import MEDIA_PURPOSE_DESKTOP_FEEDBACK, MEDIA_PURPOSE_EMAIL
from posthog.ph_client import PH_US_API_KEY

from products.surveys.backend.desktop_feedback import (
    DESKTOP_FEEDBACK_MEDIA_RETENTION,
    sweep_expired_desktop_feedback_media,
)


def _image_file(name: str = "example.png", image_format: str = "PNG") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(buffer, format=image_format)
    content_types = {"PNG": "image/png", "TIFF": "image/tiff"}
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_types[image_format])


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestDesktopFeedback(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.internal_org = Organization.objects.create(name="PostHog internal")
        self.internal_team = Team.objects.create(
            organization=self.internal_org,
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
        assert media.purpose == MEDIA_PURPOSE_DESKTOP_FEEDBACK
        properties = client.capture.call_args.kwargs["properties"]
        assert properties["$survey_id"] == "019ee235-2e3b-0000-64b3-5f2efa487452"
        assert properties["$survey_response_68648b23-caaf-4080-ae5f-051513d3097f"] == "The page did not load"
        attachment_path = urlsplit(properties["feedback_screenshot_url"]).path
        assert attachment_path == f"/api/desktop_feedback/attachments/{media.id}/"
        assert properties["feedback_app_logs"] == "[info] Example log"
        assert properties["$session_id"] == "00000000-0000-0000-0000-000000000002"

        assert self.client.get(media.get_absolute_url()).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(attachment_path).status_code == status.HTTP_404_NOT_FOUND

        OrganizationMembership.objects.create(
            organization=self.internal_org,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )
        with patch(
            "products.surveys.backend.desktop_feedback.object_storage.read_bytes",
            return_value=b"private image",
        ):
            attachment_response = self.client.get(attachment_path)

        assert attachment_response.status_code == status.HTTP_200_OK
        assert attachment_response.content == b"private image"
        assert attachment_response.headers["Cache-Control"] == "private, no-store"

        UploadedMedia.objects.filter(pk=media.pk).update(
            created_at=timezone.now() - DESKTOP_FEEDBACK_MEDIA_RETENTION - timedelta(seconds=1)
        )
        assert self.client.get(attachment_path).status_code == status.HTTP_404_NOT_FOUND

    @patch("products.surveys.backend.desktop_feedback.get_client")
    def test_rejects_unsupported_image_formats_as_invalid_input(self, get_client) -> None:
        response = self.client.post(
            "/api/desktop_feedback/",
            {
                "response": "The page did not load",
                "source": "Generic (Leave feedback button)",
                "feedback_view": "task-detail",
                "screenshot": _image_file("screenshot.tiff", "TIFF"),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "invalid_image"
        assert not UploadedMedia.objects.exists()
        get_client.assert_not_called()

    @patch("products.surveys.backend.desktop_feedback.object_storage.delete")
    def test_removes_feedback_media_after_retention(self, delete_object) -> None:
        expired = UploadedMedia.objects.create(
            team=self.internal_team,
            created_by=self.user,
            file_name="expired.jpg",
            content_type="image/jpeg",
            media_location=f"media_uploads/team-{self.internal_team.pk}/media-expired",
            purpose=MEDIA_PURPOSE_DESKTOP_FEEDBACK,
        )
        current = UploadedMedia.objects.create(
            team=self.internal_team,
            created_by=self.user,
            file_name="current.jpg",
            content_type="image/jpeg",
            media_location=f"media_uploads/team-{self.internal_team.pk}/media-current",
            purpose=MEDIA_PURPOSE_DESKTOP_FEEDBACK,
        )
        other_media = UploadedMedia.objects.create(
            team=self.internal_team,
            created_by=self.user,
            file_name="library.jpg",
            content_type="image/jpeg",
            media_location=f"media_uploads/team-{self.internal_team.pk}/media-library",
            purpose=MEDIA_PURPOSE_EMAIL,
        )
        UploadedMedia.objects.filter(pk__in=[expired.pk, other_media.pk]).update(
            created_at=timezone.now() - DESKTOP_FEEDBACK_MEDIA_RETENTION - timedelta(seconds=1)
        )

        assert sweep_expired_desktop_feedback_media() == 1

        assert not UploadedMedia.objects.filter(pk=expired.pk).exists()
        assert UploadedMedia.objects.filter(pk=current.pk).exists()
        assert UploadedMedia.objects.filter(pk=other_media.pk).exists()
        delete_object.assert_called_once_with(expired.media_location)

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

    @override_settings(CLOUD_DEPLOYMENT="EU")
    @patch("products.surveys.backend.desktop_feedback.get_client")
    def test_captures_feedback_in_the_instance_region(self, get_client) -> None:
        client = MagicMock()
        client.capture.return_value = "00000000-0000-0000-0000-000000000001"
        get_client.return_value = client

        response = self.client.post(
            "/api/desktop_feedback/",
            {
                "response": "The page did not load",
                "source": "Generic (Leave feedback button)",
                "feedback_view": "task-detail",
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        get_client.assert_called_once_with(
            "EU",
            sync_mode=True,
            capture_mode="v1",
            timeout=5,
            max_retries=2,
        )

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
