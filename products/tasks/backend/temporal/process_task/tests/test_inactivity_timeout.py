from datetime import timedelta

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.constants import (
    INACTIVITY_TIMEOUT_TEST_SECONDS,
    MAX_INACTIVITY_TIMEOUT_SECONDS,
    resolve_inactivity_timeout,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


class TestResolveInactivityTimeout(SimpleTestCase):
    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_production_default_is_the_profile_idle_window(self):
        self.assertEqual(resolve_inactivity_timeout(idle_minutes=7), timedelta(minutes=7))

    @parameterized.expand(
        [
            ("user_created", Task.OriginProduct.USER_CREATED.value, None, 60),
            ("missing_origin", None, None, 60),
            ("image_builder", Task.OriginProduct.IMAGE_BUILDER.value, None, 60),
            ("space_setup", Task.OriginProduct.SPACE_SETUP.value, None, 60),
            ("signals_scout", Task.OriginProduct.SIGNALS_SCOUT.value, None, 30),
            ("posthog_ai", Task.OriginProduct.POSTHOG_AI.value, None, 10),
            ("explicit_profile", Task.OriginProduct.POSTHOG_AI.value, "posthog_ai.imported", 10),
        ]
    )
    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_context_resolves_its_idle_window_from_the_task_profile(
        self, _name, origin_product, profile_key, expected_minutes
    ):
        context = TaskProcessingContext(
            task_id="task-id",
            run_id="run-id",
            team_id=1,
            team_uuid="team-uuid",
            organization_id="org-id",
            github_integration_id=123,
            repository="explore-science/paper-wizard-frontend",
            distinct_id="distinct",
            origin_product=origin_product,
            profile_key=profile_key,
        )
        self.assertEqual(context.inactivity_timeout(), timedelta(minutes=expected_minutes))

    @parameterized.expand([("user", 60), ("default", 30), ("posthog_ai", 10)])
    @override_settings(TEST=True, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_test_default_is_short_regardless_of_idle_window(self, _name, idle_minutes):
        result = resolve_inactivity_timeout(idle_minutes=idle_minutes)
        self.assertEqual(result, timedelta(seconds=INACTIVITY_TIMEOUT_TEST_SECONDS))

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=42)
    def test_per_task_override_wins_over_env_override(self):
        result = resolve_inactivity_timeout(idle_minutes=60, state={"inactivity_timeout_seconds": 999})
        self.assertEqual(result, timedelta(seconds=999))

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=42)
    def test_env_override_applies_when_state_has_no_per_task_override(self):
        result = resolve_inactivity_timeout(idle_minutes=60, state={})
        self.assertEqual(result, timedelta(seconds=42))

    @override_settings(TEST=True, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_per_task_override_wins_over_test_default(self):
        result = resolve_inactivity_timeout(idle_minutes=30, state={"inactivity_timeout_seconds": 1234})
        self.assertEqual(result, timedelta(seconds=1234))

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_per_task_override_is_clamped_to_max(self):
        result = resolve_inactivity_timeout(
            idle_minutes=60, state={"inactivity_timeout_seconds": MAX_INACTIVITY_TIMEOUT_SECONDS * 10}
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
    def test_invalid_per_task_override_falls_back_to_profile_default(self, _name, value):
        state = {"inactivity_timeout_seconds": value} if value is not None else {}
        result = resolve_inactivity_timeout(idle_minutes=60, state=state)
        self.assertEqual(result, timedelta(minutes=60))
