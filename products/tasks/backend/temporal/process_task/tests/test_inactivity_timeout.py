from datetime import timedelta

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.constants import (
    INACTIVITY_TIMEOUT_DEFAULT_SECONDS,
    INACTIVITY_TIMEOUT_TEST_SECONDS,
    INACTIVITY_TIMEOUT_USER_SECONDS,
    MAX_INACTIVITY_TIMEOUT_SECONDS,
    POSTHOG_AI_IDLE_TIMEOUT_SECONDS,
    POSTHOG_AI_ORIGIN_PRODUCT,
    resolve_inactivity_timeout,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


class TestResolveInactivityTimeout(SimpleTestCase):
    @parameterized.expand(
        [
            ("user_origin", True, None, INACTIVITY_TIMEOUT_USER_SECONDS),
            ("non_user_origin", False, "signals_scout", INACTIVITY_TIMEOUT_DEFAULT_SECONDS),
            ("posthog_ai", False, POSTHOG_AI_ORIGIN_PRODUCT, POSTHOG_AI_IDLE_TIMEOUT_SECONDS),
        ]
    )
    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_production_default_depends_on_origin(self, _name, is_user_origin, origin_product, expected_seconds):
        result = resolve_inactivity_timeout(is_user_origin=is_user_origin, origin_product=origin_product)
        self.assertEqual(result, timedelta(seconds=expected_seconds))

    def test_posthog_ai_origin_constant_matches_model_enum(self):
        self.assertEqual(POSTHOG_AI_ORIGIN_PRODUCT, Task.OriginProduct.POSTHOG_AI.value)

    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_context_forwards_its_origin_to_the_resolver(self):
        # Guards the wiring, not the resolver: dropping `origin_product=` at this call site
        # would leave every resolver case green while PostHog AI silently fell back to 30 minutes.
        context = TaskProcessingContext(
            task_id="task-id",
            run_id="run-id",
            team_id=1,
            team_uuid="team-uuid",
            organization_id="org-id",
            github_integration_id=123,
            repository="explore-science/paper-wizard-frontend",
            distinct_id="distinct",
            origin_product=POSTHOG_AI_ORIGIN_PRODUCT,
        )
        self.assertEqual(context.inactivity_timeout(), timedelta(seconds=POSTHOG_AI_IDLE_TIMEOUT_SECONDS))

    @override_settings(TEST=True, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_test_default_is_short_regardless_of_origin(self):
        for is_user_origin, origin_product in ((True, None), (False, None), (False, POSTHOG_AI_ORIGIN_PRODUCT)):
            result = resolve_inactivity_timeout(is_user_origin=is_user_origin, origin_product=origin_product)
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
