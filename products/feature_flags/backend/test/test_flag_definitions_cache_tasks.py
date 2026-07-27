from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.test.utils import PushGatewayTaskTestMixin

from products.feature_flags.backend.tasks import (
    cleanup_stale_flag_definitions_expiry_tracking_task,
    refresh_expiring_flag_definitions_cache_entries,
)


class TestRefreshExpiringFlagDefinitionsCacheEntries(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.storage.cache_expiry_manager.refresh_expiring_caches")
    def test_refreshes_cache(self, mock_refresh: MagicMock) -> None:
        mock_refresh.return_value = (5, 0)

        refresh_expiring_flag_definitions_cache_entries()

        mock_refresh.assert_called_once()

    @patch("posthog.storage.cache_expiry_manager.refresh_expiring_caches")
    def test_propagates_error(self, mock_refresh: MagicMock) -> None:
        mock_refresh.side_effect = Exception("refresh failed")

        with self.assertRaises(Exception):
            refresh_expiring_flag_definitions_cache_entries()


class TestCleanupStaleFlagDefinitionsExpiryTrackingTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.storage.cache_expiry_manager.cleanup_stale_expiry_tracking")
    def test_cleans_up_cache(self, mock_cleanup: MagicMock) -> None:
        mock_cleanup.return_value = 3

        cleanup_stale_flag_definitions_expiry_tracking_task()

        mock_cleanup.assert_called_once()

    @patch("posthog.storage.cache_expiry_manager.cleanup_stale_expiry_tracking")
    def test_propagates_error(self, mock_cleanup: MagicMock) -> None:
        mock_cleanup.side_effect = Exception("cleanup failed")

        with self.assertRaises(Exception):
            cleanup_stale_flag_definitions_expiry_tracking_task()
