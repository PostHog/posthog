from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.tasks.backend import redis as tasks_redis


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
