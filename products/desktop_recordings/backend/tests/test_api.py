from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.desktop_recordings.backend.models import DesktopRecording, RecordingTranscript


class TestDesktopRecordingAPI(APIBaseTest):
    """Test the desktop recording REST API that Array desktop app uses"""

    def test_create_upload_returns_token_and_creates_recording(self):
        """Array calls create_upload to get Recall.ai token, PostHog creates recording"""
        mock_recall_response = {"id": str(uuid4()), "upload_token": "test-upload-token-123"}

        with patch("products.desktop_recordings.backend.api.RecallAIClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.create_sdk_upload.return_value = mock_recall_response
            mock_client.return_value = mock_instance

            response = self.client.post(
                f"/api/environments/{self.team.id}/desktop_recordings/create_upload/",
                {"platform": "zoom"},
                format="json",
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["upload_token"] == "test-upload-token-123"
            assert "recording_id" in data

            # Verify recording created with correct status
            recording = DesktopRecording.objects.get(id=data["recording_id"])
            assert recording.team == self.team
            assert recording.created_by == self.user
            assert recording.platform == "zoom"
            assert recording.status == DesktopRecording.Status.RECORDING
            assert str(recording.sdk_upload_id) == mock_recall_response["id"]

    def test_create_upload_returns_503_when_api_key_missing(self):
        """Create upload should fail gracefully when Recall.ai API key not configured"""
        from unittest.mock import patch

        with patch("posthog.settings.integrations.RECALL_AI_API_KEY", ""):
            response = self.client.post(
                f"/api/environments/{self.team.id}/desktop_recordings/create_upload/",
                {"platform": "zoom"},
                format="json",
            )

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "not configured" in response.json()["detail"]

    def test_upload_transcript_creates_transcript_and_completes_recording(self):
        """Array uploads transcript after getting it from Recall.ai"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )

        transcript_data = {
            "full_text": "This is the meeting transcript",
            "segments": [
                {"text": "This is", "start": 0.0, "end": 1.5, "speaker": "Alice"},
                {"text": "the meeting transcript", "start": 1.5, "end": 3.0, "speaker": "Bob"},
            ],
            "extracted_tasks": [
                {"title": "Follow up with customer", "description": "Send proposal by Friday"},
            ],
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/upload_transcript/",
            transcript_data,
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["full_text"] == "This is the meeting transcript"
        assert len(data["segments"]) == 2
        assert len(data["extracted_tasks"]) == 1

        # Verify transcript created and recording marked complete
        recording.refresh_from_db()
        assert recording.status == DesktopRecording.Status.COMPLETE
        assert hasattr(recording, "transcript")
        assert recording.transcript.full_text == "This is the meeting transcript"

    def test_upload_transcript_is_idempotent(self):
        """Uploading transcript multiple times should update, not error"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )

        # First upload
        response1 = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/upload_transcript/",
            {"full_text": "First version", "segments": [], "extracted_tasks": []},
            format="json",
        )
        assert response1.status_code == status.HTTP_201_CREATED

        # Second upload - should update
        response2 = self.client.post(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/upload_transcript/",
            {"full_text": "Updated version", "segments": [], "extracted_tasks": []},
            format="json",
        )
        assert response2.status_code == status.HTTP_200_OK
        assert response2.json()["full_text"] == "Updated version"

        # Should only have one transcript
        assert RecordingTranscript.objects.filter(recording=recording).count() == 1

    def test_update_recording_metadata(self):
        """Array can update recording metadata via PATCH"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/",
            {
                "recall_recording_id": str(uuid4()),
                "meeting_title": "Q4 Planning Meeting",
                "duration_seconds": 1800,
                "participants": [{"name": "Alice"}, {"name": "Bob"}],
                "status": "complete",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        recording.refresh_from_db()
        assert recording.meeting_title == "Q4 Planning Meeting"
        assert recording.duration_seconds == 1800
        assert len(recording.participants) == 2
        assert recording.status == DesktopRecording.Status.COMPLETE

    def test_list_recordings_filters_by_team(self):
        """Recordings are isolated by team"""
        recording1 = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.COMPLETE,
        )

        # Create recording for different team
        other_team = self.organization.teams.create(name="Other Team")
        DesktopRecording.objects.create(
            team=other_team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="teams",
            status=DesktopRecording.Status.COMPLETE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/desktop_recordings/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(recording1.id)

    def test_filter_by_status(self):
        """List endpoint can filter by status"""
        complete = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.COMPLETE,
        )

        DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="teams",
            status=DesktopRecording.Status.RECORDING,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/desktop_recordings/?status=complete")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(complete.id)

    def test_search_transcript_text(self):
        """Can search across transcript full_text"""
        recording1 = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
        )
        RecordingTranscript.objects.create(
            recording=recording1,
            full_text="We need to increase our conversion rate by optimizing the checkout flow",
            segments=[],
        )

        recording2 = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="teams",
        )
        RecordingTranscript.objects.create(
            recording=recording2,
            full_text="The new feature launch is scheduled for next week",
            segments=[],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/desktop_recordings/?search=conversion")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(recording1.id)

    def test_get_transcript(self):
        """Can retrieve transcript for a recording"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
        )

        RecordingTranscript.objects.create(
            recording=recording,
            full_text="Meeting transcript",
            segments=[{"text": "Meeting transcript", "start": 0, "end": 5}],
            extracted_tasks=[{"title": "Task 1"}],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["full_text"] == "Meeting transcript"
        assert len(data["segments"]) == 1
        assert len(data["extracted_tasks"]) == 1

    def test_get_transcript_returns_404_when_not_available(self):
        """Getting transcript before Array uploads it returns 404"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform="zoom",
            status=DesktopRecording.Status.RECORDING,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/desktop_recordings/{recording.id}/transcript/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not yet available" in response.json()["detail"]
