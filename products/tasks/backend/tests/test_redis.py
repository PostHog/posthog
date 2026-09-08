from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import redis.exceptions

from products.tasks.backend.redis import tasks_cache_add, tasks_cache_get, tasks_cache_set


class TestTasksCacheDegradation(SimpleTestCase):
    def _failing_cache(self) -> MagicMock:
        cache = MagicMock()
        # BusyLoadingError is the error Redis raises while reloading its dataset on failover.
        err = redis.exceptions.BusyLoadingError("Redis is loading the dataset in memory")
        cache.get.side_effect = err
        cache.set.side_effect = err
        cache.add.side_effect = err
        return cache

    @patch("products.tasks.backend.redis.get_tasks_cache")
    def test_get_returns_default_on_redis_error(self, mock_get_cache: MagicMock) -> None:
        mock_get_cache.return_value = self._failing_cache()
        self.assertIsNone(tasks_cache_get("k"))
        self.assertEqual(tasks_cache_get("k", "fallback"), "fallback")

    @patch("products.tasks.backend.redis.get_tasks_cache")
    def test_set_swallows_redis_error(self, mock_get_cache: MagicMock) -> None:
        mock_get_cache.return_value = self._failing_cache()
        tasks_cache_set("k", "v", timeout=60)

    @patch("products.tasks.backend.redis.get_tasks_cache")
    def test_add_returns_on_error_value(self, mock_get_cache: MagicMock) -> None:
        mock_get_cache.return_value = self._failing_cache()
        # The caller chooses whether a cache blip means "proceed" or "skip the follow-on action".
        self.assertTrue(tasks_cache_add("k", True, timeout=60, on_error=True))
        self.assertFalse(tasks_cache_add("k", True, timeout=60, on_error=False))
