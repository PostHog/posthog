from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from posthog.storage.cache_expiry_manager import CacheRefreshCounts
from posthog.tasks.test.utils import PushGatewayTaskTestMixin

from products.feature_flags.backend.local_evaluation import FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG
from products.feature_flags.backend.tasks import (
    cleanup_stale_flag_definitions_expiry_tracking_task,
    refresh_expiring_flag_definitions_cache_entries,
    refresh_expiring_flags_cache_entries,
)


class TestRefreshExpiringFlagDefinitionsCacheEntries(PushGatewayTaskTestMixin, TestCase):
    @patch("products.feature_flags.backend.tasks.get_cache_stats_generic", return_value={})
    @patch("posthog.storage.cache_expiry_manager.refresh_expiring_caches")
    def test_refreshes_cache(self, mock_refresh: MagicMock, mock_stats: MagicMock) -> None:
        mock_refresh.return_value = CacheRefreshCounts(successful=5, failed=0)

        refresh_expiring_flag_definitions_cache_entries()

        mock_refresh.assert_called_once_with(
            config=FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
            ttl_threshold_hours=settings.FLAG_DEFINITIONS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
            limit=settings.FLAG_DEFINITIONS_CACHE_REFRESH_LIMIT,
        )
        assert settings.FLAG_DEFINITIONS_CACHE_REFRESH_LIMIT == settings.FLAGS_CACHE_REFRESH_LIMIT
        assert (
            settings.FLAG_DEFINITIONS_CACHE_REFRESH_TTL_THRESHOLD_HOURS
            == settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS
        )
        assert self.registry.get_sample_value("posthog_flag_definitions_cache_refresh_successful_count") == 5
        assert self.registry.get_sample_value("posthog_flag_definitions_cache_refresh_failed_count") == 0
        mock_stats.assert_called_once_with(FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG)

    @override_settings(
        FLAG_DEFINITIONS_CACHE_REFRESH_LIMIT=7,
        FLAG_DEFINITIONS_CACHE_REFRESH_TTL_THRESHOLD_HOURS=3,
        FLAGS_REDIS_URL="redis://localhost:6379",
    )
    @patch("products.feature_flags.backend.tasks.get_cache_stats", return_value={})
    @patch("products.feature_flags.backend.tasks.refresh_expiring_flags_caches")
    @patch("products.feature_flags.backend.tasks.get_cache_stats_generic", return_value={})
    @patch("posthog.storage.cache_expiry_manager.refresh_expiring_caches")
    def test_definitions_settings_leave_the_flags_sweep_alone(
        self,
        mock_definitions_refresh: MagicMock,
        mock_definitions_stats: MagicMock,
        mock_flags_refresh: MagicMock,
        mock_flags_stats: MagicMock,
    ) -> None:
        mock_definitions_refresh.return_value = CacheRefreshCounts(successful=1, failed=0)
        mock_flags_refresh.return_value = CacheRefreshCounts(successful=1, failed=0)

        refresh_expiring_flag_definitions_cache_entries()
        refresh_expiring_flags_cache_entries()

        assert mock_definitions_refresh.call_args.kwargs["limit"] == 7
        assert mock_definitions_refresh.call_args.kwargs["ttl_threshold_hours"] == 3
        assert mock_flags_refresh.call_args.kwargs["limit"] == settings.FLAGS_CACHE_REFRESH_LIMIT
        assert (
            mock_flags_refresh.call_args.kwargs["ttl_threshold_hours"]
            == settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS
        )

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
