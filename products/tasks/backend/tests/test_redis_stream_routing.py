from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from products.tasks.backend import redis as tasks_redis

CUTOVER = datetime(2026, 6, 9, tzinfo=UTC)
AFTER = CUTOVER + timedelta(seconds=1)
BEFORE = CUTOVER - timedelta(seconds=1)


@patch.object(tasks_redis, "TASKS_REDIS_STREAM_CUTOVER_AT", CUTOVER)
class TestStreamRouting(SimpleTestCase):
    @override_settings(TASKS_REDIS_URL=None, REDIS_URL="redis://shared")
    def test_no_dedicated_url_always_uses_shared(self):
        self.assertFalse(tasks_redis._use_dedicated_stream(AFTER))
        self.assertEqual(tasks_redis._tasks_stream_redis_url(AFTER), "redis://shared")

    @override_settings(TASKS_REDIS_URL="redis://dedicated", REDIS_URL="redis://shared")
    def test_routes_by_cutover(self):
        self.assertTrue(tasks_redis._use_dedicated_stream(CUTOVER))
        self.assertTrue(tasks_redis._use_dedicated_stream(AFTER))
        self.assertFalse(tasks_redis._use_dedicated_stream(BEFORE))

        self.assertEqual(tasks_redis._tasks_stream_redis_url(AFTER), "redis://dedicated")
        self.assertEqual(tasks_redis._tasks_stream_redis_url(BEFORE), "redis://shared")

    @override_settings(TASKS_REDIS_URL="redis://dedicated", REDIS_URL="redis://shared")
    def test_missing_created_at_uses_shared(self):
        # Unknown created_at must not move a stream onto the dedicated instance.
        self.assertFalse(tasks_redis._use_dedicated_stream(None))
        self.assertEqual(tasks_redis._tasks_stream_redis_url(None), "redis://shared")
