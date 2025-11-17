from uuid import uuid4

from posthog.test.base import BaseTest

from products.desktop_recordings.backend.models import DesktopRecording


class TestDesktopRecordingModel(BaseTest):
    """Test desktop recording model business logic"""

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
