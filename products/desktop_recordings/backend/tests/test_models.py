from uuid import uuid4

from posthog.test.base import BaseTest

from django.db import IntegrityError

from products.desktop_recordings.backend.models import DesktopRecording, RecordingTranscript


class TestDesktopRecordingModel(BaseTest):
    """Test desktop recording model business logic"""

    def test_transcript_one_to_one_relationship(self):
        """A recording can only have one transcript (enforced by OneToOneField)"""
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform=DesktopRecording.Platform.ZOOM,
        )

        transcript = RecordingTranscript.objects.create(
            recording=recording,
            full_text="First transcript",
            segments=[],
        )

        # Access transcript via recording
        assert recording.transcript == transcript
        assert recording.transcript.full_text == "First transcript"

        # Attempting to create a second transcript should raise IntegrityError
        with self.assertRaises(IntegrityError):
            RecordingTranscript.objects.create(
                recording=recording,
                full_text="Second transcript",
                segments=[],
            )

    def test_recordings_ordered_by_most_recent(self):
        """Recordings should be ordered by started_at descending"""
        recording1 = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform=DesktopRecording.Platform.ZOOM,
        )

        recording2 = DesktopRecording.objects.create(
            team=self.team,
            created_by=self.user,
            sdk_upload_id=uuid4(),
            platform=DesktopRecording.Platform.TEAMS,
        )

        recordings = list(DesktopRecording.objects.filter(team=self.team))
        # Most recent first
        assert recordings[0].id == recording2.id
        assert recordings[1].id == recording1.id
