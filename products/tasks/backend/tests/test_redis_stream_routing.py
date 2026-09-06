import asyncio
import concurrent.futures

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import redis.exceptions
from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.tasks.backend import redis as tasks_redis
from products.tasks.backend.logic.stream import redis_stream


class TestStreamRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("dedicated_set_pinned", "redis://dedicated", True, "redis://dedicated"),
            ("dedicated_set_unpinned", "redis://dedicated", False, "redis://shared"),
            ("no_dedicated_pinned", None, True, "redis://shared"),
            ("no_dedicated_unpinned", None, False, "redis://shared"),
        ]
    )
    def test_tasks_stream_redis_url(self, _name, dedicated_url, use_dedicated, expected):
        with override_settings(TASKS_REDIS_URL=dedicated_url, REDIS_URL="redis://shared"):
            self.assertEqual(tasks_redis._tasks_stream_redis_url(use_dedicated), expected)

    @parameterized.expand(
        [
            ("pinned_true", {"use_dedicated_stream": True}, True),
            ("pinned_false", {"use_dedicated_stream": False}, False),
            ("missing_key", {}, False),
            ("none_state", None, False),
        ]
    )
    def test_run_uses_dedicated_stream(self, _name, state, expected):
        self.assertEqual(tasks_redis.run_uses_dedicated_stream(state), expected)


class TestEvaluateDedicatedStreamFlag(SimpleTestCase):
    @override_settings(TASKS_REDIS_URL=None)
    def test_returns_false_without_dedicated_url(self):
        with patch.object(tasks_redis.posthoganalytics, "feature_enabled") as mock_flag:
            self.assertFalse(tasks_redis.evaluate_dedicated_stream_flag(organization_id="org", distinct_id="u"))
            mock_flag.assert_not_called()

    @parameterized.expand([("flag_on", True, True), ("flag_off", False, False)])
    def test_returns_flag_value_when_url_present(self, _name, flag_value, expected):
        with override_settings(TASKS_REDIS_URL="redis://dedicated"):
            with patch.object(tasks_redis.posthoganalytics, "feature_enabled", return_value=flag_value):
                self.assertEqual(
                    tasks_redis.evaluate_dedicated_stream_flag(organization_id="org", distinct_id="u"), expected
                )

    @override_settings(TASKS_REDIS_URL="redis://dedicated")
    def test_fails_safe_to_shared_on_flag_error(self):
        with patch.object(tasks_redis.posthoganalytics, "feature_enabled", side_effect=RuntimeError("boom")):
            self.assertFalse(tasks_redis.evaluate_dedicated_stream_flag(organization_id="org", distinct_id="u"))


class TestTasksCacheAddRedisFallback(SimpleTestCase):
    def test_add_degrades_to_per_process_guard(self):
        # A guard that fails open during an outage disables the heartbeat throttle and the push
        # cooldown on every process, so a redis failure must dedup per process instead.
        failing_cache = MagicMock()
        failing_cache.add.side_effect = redis.exceptions.BusyLoadingError()

        with (
            patch.object(tasks_redis, "get_tasks_cache", return_value=failing_cache),
            patch.object(tasks_redis, "capture_exception") as mock_capture,
            patch.object(tasks_redis, "_next_capture_at", 0.0),
            patch.dict(tasks_redis._local_guard_expiry, clear=True),
            patch("products.tasks.backend.redis.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 1000.0
            self.assertTrue(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))
            self.assertFalse(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))
            self.assertTrue(tasks_redis.tasks_cache_add("other-key", True, timeout=60))
            mock_capture.assert_called_once()

            mock_time.monotonic.return_value = 1061.0
            self.assertTrue(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))

    @parameterized.expand(
        [
            ("redis_admit_then_outage", [True, redis.exceptions.ConnectionError()]),
            ("outage_admit_then_redis_recovered", [redis.exceptions.ConnectionError(), True]),
        ]
    )
    def test_boundary_admission_is_not_duplicated(self, _name, add_results):
        # At each redis/fallback boundary the same key must admit once. If a redis admission is
        # not recorded locally, the second call across the boundary returns True again and
        # delivers a duplicate push for the same cooldown key.
        cache = MagicMock()
        cache.add.side_effect = add_results

        with (
            patch.object(tasks_redis, "get_tasks_cache", return_value=cache),
            patch.object(tasks_redis, "capture_exception"),
            patch.object(tasks_redis, "_next_capture_at", 0.0),
            patch.dict(tasks_redis._local_guard_expiry, clear=True),
            patch("products.tasks.backend.redis.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 1000.0
            self.assertTrue(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))
            self.assertFalse(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))

    def test_recovery_mid_window_does_not_extend_suppression(self):
        # A call the guard vetoes must not write redis. A redis key that outlives the guard entry
        # pushes the next admission out to nearly two windows, and the 60s heartbeat guard has
        # only a 2x margin before the 120s inactivity timer ends an unattended run.
        cache = MagicMock()
        cache.add.side_effect = [redis.exceptions.ConnectionError(), True]

        with (
            patch.object(tasks_redis, "get_tasks_cache", return_value=cache),
            patch.object(tasks_redis, "capture_exception"),
            patch.object(tasks_redis, "_next_capture_at", 0.0),
            patch.dict(tasks_redis._local_guard_expiry, clear=True),
            patch("products.tasks.backend.redis.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 1000.0
            self.assertTrue(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))

            mock_time.monotonic.return_value = 1059.0
            self.assertFalse(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))
            self.assertEqual(cache.add.call_count, 1)

            mock_time.monotonic.return_value = 1061.0
            self.assertTrue(tasks_redis.tasks_cache_add("guard-key", True, timeout=60))


class _ThreadHungryAsyncClient:
    """Async Redis stand-in whose ops need a default-executor thread to finish.

    Mirrors real asyncio Redis: connecting resolves the host via
    loop.run_in_executor(None, getaddrinfo), so each op consumes a thread from the
    same bounded pool the activity bodies run on.
    """

    async def _needs_thread(self, value):
        return await asyncio.get_running_loop().run_in_executor(None, lambda: value)

    async def xadd(self, *args, **kwargs):
        return await self._needs_thread("1-0")

    async def expire(self, *args, **kwargs):
        return await self._needs_thread(True)


class TestSyncPublishDoesNotStarveExecutor(SimpleTestCase):
    def test_publish_event_does_not_deadlock_bounded_executor(self):
        # Asyncified activities run their body on the event loop's bounded default
        # ThreadPoolExecutor (sync_to_async(thread_sensitive=False)). A regression to
        # async_to_sync over the async client would bounce back to the loop and need a
        # *second* executor thread, so once concurrent bodies fill the pool nothing
        # completes. The async client is patched to be thread-hungry precisely to catch
        # that: the fix uses the sync client and never touches it (asserted below), so
        # this run completes; a revert would use it and deadlock this gather().
        workers = 4
        n = workers + 4

        async def main():
            asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=workers))

            async def body(i):
                return await sync_to_async(redis_stream.publish_task_run_stream_event, thread_sensitive=False)(
                    "run-under-test", {"type": "probe", "i": i}, False
                )

            return await asyncio.wait_for(asyncio.gather(*(body(i) for i in range(n))), timeout=15)

        with patch.object(
            redis_stream, "get_tasks_stream_redis_async", return_value=_ThreadHungryAsyncClient()
        ) as async_client:
            results = asyncio.run(main())

        async_client.assert_not_called()  # sync publish path must not build the async client
        self.assertEqual(len(results), n)
        self.assertTrue(all(r is not None for r in results))
