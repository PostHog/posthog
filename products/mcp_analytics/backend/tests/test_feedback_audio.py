from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from openai import OpenAIError
from parameterized import parameterized
from rest_framework.response import Response

from posthog.models import Organization, Team

from products.mcp_analytics.backend.feedback_audio import FeedbackTranscriber
from products.mcp_analytics.backend.presentation.feedback_audio import FeedbackAudioRequestSerializer


class TestFeedbackAudioValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("audio/webm", 10, True),
            ("audio/mp4", 10, True),
            ("audio/ogg", 10, True),
            ("text/html", 10, False),
            ("audio/webm", 0, False),
            ("audio/webm", 5 * 1024 * 1024 + 1, False),
        ]
    )
    def test_audio_validation(self, content_type: str, size: int, valid: bool) -> None:
        audio = SimpleUploadedFile("feedback", b"x" * size, content_type=content_type)
        serializer = FeedbackAudioRequestSerializer(data={"audio": audio})
        self.assertEqual(serializer.is_valid(), valid)

    @override_settings(OPENAI_API_KEY="fake-key", OPENAI_BASE_URL="https://example.com/v1")
    @patch("products.mcp_analytics.backend.feedback_audio.OpenAI")
    def test_transcribes_bytes_without_forwarding_the_uploaded_filename(self, client: MagicMock) -> None:
        transcriptions = client.return_value.__enter__.return_value.audio.transcriptions
        transcriptions.create.return_value.text = "  I found the failing call.  "
        result = FeedbackTranscriber.transcribe(
            SimpleUploadedFile("private-name.webm", b"audio", content_type="audio/webm")
        )
        self.assertEqual(result, "I found the failing call.")
        self.assertEqual(transcriptions.create.call_args.kwargs["file"], ("feedback.webm", b"audio", "audio/webm"))


@override_settings(OPENAI_API_KEY="fake-key")
class TestFeedbackAudioAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def upload(self, content_type: str = "audio/webm", team_id: int | None = None) -> Response:
        return self.client.post(
            f"/api/projects/{team_id or self.team.id}/mcp_analytics/feedback_audio/",
            {"audio": SimpleUploadedFile("feedback.webm", b"audio", content_type=content_type)},
            format="multipart",
        )

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.mcp_analytics.backend.feedback_audio.FeedbackTranscriber.transcribe")
    def test_transcription_and_input_validation(self, transcribe: MagicMock, feature_enabled: MagicMock) -> None:
        transcribe.return_value = "I found the failing call."
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "I found the failing call."})
        self.assertEqual(self.upload("text/html").status_code, 400)
        transcribe.assert_called_once()

    @parameterized.expand([("flag",), ("consent",), ("authentication",)])
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.mcp_analytics.backend.feedback_audio.FeedbackTranscriber.transcribe")
    def test_rejects_before_contacting_provider(
        self, denied: str, transcribe: MagicMock, feature_enabled: MagicMock
    ) -> None:
        if denied == "flag":
            feature_enabled.return_value = False
        elif denied == "consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        else:
            self.client.logout()
        self.assertIn(self.upload().status_code, [401, 403])
        transcribe.assert_not_called()

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch(
        "products.mcp_analytics.backend.feedback_audio.FeedbackTranscriber.transcribe",
        side_effect=OpenAIError("provider failure"),
    )
    def test_provider_failure_keeps_a_retryable_response(
        self, transcribe: MagicMock, feature_enabled: MagicMock
    ) -> None:
        response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("provider failure", response.json()["detail"])

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.mcp_analytics.backend.feedback_audio.FeedbackTranscriber.transcribe")
    def test_other_project_and_rate_limit_reject_before_transcribing(
        self, transcribe: MagicMock, feature_enabled: MagicMock
    ) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Example organization"))
        self.assertIn(self.upload(team_id=other_team.id).status_code, [403, 404])
        transcribe.assert_not_called()
        transcribe.return_value = "I found the failed call."
        for _ in range(5):
            self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload().status_code, 429)
        self.assertEqual(transcribe.call_count, 5)
