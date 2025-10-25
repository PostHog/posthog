from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.desktop_recordings.backend.models import DesktopRecording, RecordingTranscript


class TestDesktopRecordingAPI(APIBaseTest):
    """Test the desktop recording REST API that Array desktop app uses"""

    def test_create_recording_returns_token_and_auto_creates_transcript(self):
        """RESTful POST creates recording with upload token and empty transcript"""
        mock_recall_response = {"id": str(uuid4()), "upload_token": "test-upload-token-123"}

        with patch("products.desktop_recordings.backend.api.RecallAIClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.create_sdk_upload.return_value = mock_recall_response
            mock_client.return_value = mock_instance

            response = self.client.post(
                f"/api/environments/{self.team.id}/desktop_recordings/",
                {"platform": "zoom"},
                format="json",
            )

            assert response.status_code == status.HTTP_201_CREATED
            data = response.json()
            assert data["upload_token"] == "test-upload-token-123"
            assert "id" in data

            # Verify recording created with correct status
            recording = DesktopRecording.objects.get(id=data["id"])
            assert recording.team == self.team
            assert recording.created_by == self.user
            assert recording.platform == "zoom"
            assert recording.status == DesktopRecording.Status.RECORDING
            assert str(recording.sdk_upload_id) == mock_recall_response["id"]

            # Verify empty transcript auto-created
            assert hasattr(recording, "transcript")
            assert recording.transcript.full_text == ""
            assert recording.transcript.segments == []

    def test_create_recording_returns_503_when_api_key_missing(self):
        """Create recording should fail gracefully when Recall.ai API key not configured"""
        from unittest.mock import patch

        with patch("posthog.settings.integrations.RECALL_AI_API_KEY", ""):
            response = self.client.post(
                f"/api/environments/{self.team.id}/desktop_recordings/",
                {"platform": "zoom"},
                format="json",
            )

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "not configured" in response.json()["detail"]

    def test_post_transcript_appends_new_segments_with_deduplication(self):
        """POST /transcript/ appends new segments and deduplicates by timestamp"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )
        # Create empty transcript
        RecordingTranscript.objects.create(recording=recording, full_text="", segments=[])

        # First upload
        response1 = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/",
            {"segments": [{"text": "First segment", "timestamp": 0.0}]},
            format="json",
        )
        assert response1.status_code == status.HTTP_200_OK

        # Second upload - should append new segments
        response2 = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/",
            {"segments": [{"text": "Second segment", "timestamp": 1.0}]},
            format="json",
        )
        assert response2.status_code == status.HTTP_200_OK
        assert len(response2.json()["segments"]) == 2

        # Should only have one transcript with 2 segments
        assert RecordingTranscript.objects.filter(recording=recording).count() == 1
        transcript = RecordingTranscript.objects.get(recording=recording)
        assert len(transcript.segments) == 2

    def test_list_recordings_filters_by_team(self):
        """Recordings are isolated by team"""
        recording1 = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.READY,
        )

        # Create recording for different team
        other_team = self.organization.teams.create(name="Other Team")
        DesktopRecording.objects.create(
            team=other_team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="teams",
            status=DesktopRecording.Status.READY,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/desktop_recordings/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(recording1.id)

    def test_post_transcript_validates_segment_structure(self):
        """POST /transcript/ validates segment structure"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )
        RecordingTranscript.objects.create(recording=recording, full_text="", segments=[])

        # Missing required 'text' field should fail
        response = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/",
            {"segments": [{"timestamp": 0.0}]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "text" in str(response.json())

    def test_post_transcript_handles_none_timestamps(self):
        """POST /transcript/ handles segments with None timestamps"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )
        RecordingTranscript.objects.create(recording=recording, full_text="", segments=[])

        # First upload with None timestamp
        response1 = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/",
            {"segments": [{"text": "First segment", "timestamp": None}]},
            format="json",
        )
        assert response1.status_code == status.HTTP_200_OK

        # Second upload with None timestamp - should add (not deduplicate)
        response2 = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/",
            {"segments": [{"text": "Second segment", "timestamp": None}]},
            format="json",
        )
        assert response2.status_code == status.HTTP_200_OK
        assert len(response2.json()["segments"]) == 2
