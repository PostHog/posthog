from datetime import timedelta

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from posthog.storage.session_recording_v2_object_storage import BlockFetchError

from products.enterprise.backend.session_recordings.session_recording_extensions import persist_recording_v2


class TestSessionRecordingExtensions(TestCase):
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_success(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording.full_recording_v2_path = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Mock copy_to_lts to return success
        mock_copy_to_lts.return_value = "s3://bucket/lts/test_id"

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert
        mock_copy_to_lts.assert_called_once_with(mock_recording)
        mock_recording.save.assert_called_once()
        self.assertEqual(mock_recording.full_recording_v2_path, "s3://bucket/lts/test_id")

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_skips_if_too_young(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording that's too young
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=1)
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert - copy_to_lts should not be called for recordings that are too young
        mock_copy_to_lts.assert_not_called()
        mock_recording.save.assert_called_once()

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_skips_if_too_old(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording that's too old (more than 90 days old)
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(days=95)
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert - copy_to_lts should not be called for recordings that are too old
        mock_copy_to_lts.assert_not_called()
        mock_recording.save.assert_called_once()

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_skips_if_deleted(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording that's deleted
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = True
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert - copy_to_lts should not be called for deleted recordings
        mock_copy_to_lts.assert_not_called()
        mock_recording.save.assert_not_called()

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_skips_if_no_start_time(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording with no start time
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert - copy_to_lts should not be called for recordings without start time
        mock_copy_to_lts.assert_not_called()
        mock_recording.save.assert_called_once()

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_handles_copy_failure(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording.full_recording_v2_path = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Mock copy_to_lts to return None (failure)
        mock_copy_to_lts.return_value = None

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert
        mock_copy_to_lts.assert_called_once_with(mock_recording)
        mock_recording.save.assert_not_called()  # Should not save if copy failed
        self.assertIsNone(mock_recording.full_recording_v2_path)

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_handles_block_fetch_error(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording.full_recording_v2_path = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Mock copy_to_lts to raise BlockFetchError
        mock_copy_to_lts.side_effect = BlockFetchError("Failed to fetch block")

        # Execute and expect exception to bubble up
        with self.assertRaises(BlockFetchError):
            persist_recording_v2("test_id", 1)

        # Assert
        mock_copy_to_lts.assert_called_once_with(mock_recording)
        mock_recording.save.assert_not_called()
        self.assertIsNone(mock_recording.full_recording_v2_path)

    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.SessionRecording")
    @patch("products.enterprise.backend.session_recordings.session_recording_extensions.copy_to_lts")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_handles_generic_error(self, mock_copy_to_lts, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording.full_recording_v2_path = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Mock copy_to_lts to raise generic error
        mock_copy_to_lts.side_effect = Exception("Generic error")

        # Execute and expect exception to bubble up
        with self.assertRaises(Exception):
            persist_recording_v2("test_id", 1)

        # Assert
        mock_copy_to_lts.assert_called_once_with(mock_recording)
        mock_recording.save.assert_not_called()
        self.assertIsNone(mock_recording.full_recording_v2_path)
