from datetime import timedelta

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.tasks.backend.temporal.constants import (
    INACTIVITY_TIMEOUT_DEFAULT_SECONDS,
    INACTIVITY_TIMEOUT_TEST_SECONDS,
    INACTIVITY_TIMEOUT_USER_SECONDS,
    MAX_INACTIVITY_TIMEOUT_SECONDS,
    resolve_inactivity_timeout,
)


class TestResolveInactivityTimeout(SimpleTestCase):
    @parameterized.expand(
        [
            ("user_origin", True, INACTIVITY_TIMEOUT_USER_SECONDS),
            ("non_user_origin", False, INACTIVITY_TIMEOUT_DEFAULT_SECONDS),
        ]
    )
    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_production_default_depends_on_origin(self, _name, is_user_origin, expected_seconds):
        result = resolve_inactivity_timeout(is_user_origin=is_user_origin)
        self.assertEqual(result, timedelta(seconds=expected_seconds))

    @override_settings(TEST=True, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_test_default_is_short_regardless_of_origin(self):
        for is_user_origin in (True, False):
            result = resolve_inactivity_timeout(is_user_origin=is_user_origin)
            self.assertEqual(result, timedelta(seconds=INACTIVITY_TIMEOUT_TEST_SECONDS))

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=42)
    def test_per_task_override_wins_over_env_override(self):
        result = resolve_inactivity_timeout(is_user_origin=True, state={"inactivity_timeout_seconds": 999})
        self.assertEqual(result, timedelta(seconds=999))

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=42)
    def test_env_override_applies_when_state_has_no_per_task_override(self):
        result = resolve_inactivity_timeout(is_user_origin=True, state={})
        self.assertEqual(result, timedelta(seconds=42))

    @override_settings(TEST=True, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_per_task_override_wins_over_test_default(self):
        result = resolve_inactivity_timeout(is_user_origin=False, state={"inactivity_timeout_seconds": 1234})
        self.assertEqual(result, timedelta(seconds=1234))

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_per_task_override_is_clamped_to_max(self):
        result = resolve_inactivity_timeout(
            is_user_origin=True, state={"inactivity_timeout_seconds": MAX_INACTIVITY_TIMEOUT_SECONDS * 10}
        )
        self.assertEqual(result, timedelta(seconds=MAX_INACTIVITY_TIMEOUT_SECONDS))

    @parameterized.expand(
        [
            ("bool_true", True),
            ("zero", 0),
            ("negative", -5),
            ("non_numeric", "nope"),
            ("missing", None),
        ]
    )
    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_invalid_per_task_override_falls_back_to_origin_default(self, _name, value):
        state = {"inactivity_timeout_seconds": value} if value is not None else {}
        result = resolve_inactivity_timeout(is_user_origin=True, state=state)
        self.assertEqual(result, timedelta(seconds=INACTIVITY_TIMEOUT_USER_SECONDS))
