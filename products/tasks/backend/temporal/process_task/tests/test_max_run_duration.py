from datetime import timedelta

from django.test import override_settings

from products.tasks.backend.temporal.constants import MAX_RUN_DURATION_DEFAULT_SECONDS
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


def _context(state: dict | None) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="org-id",
        github_integration_id=123,
        repository="posthog/posthog-js",
        distinct_id="distinct",
        state=state,
    )


class TestMaxRunDuration:
    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=0)
    def test_interactive_sessions_are_uncapped(self):
        # A human may legitimately keep an interactive session open for hours; capping it would kill
        # a live session mid-use.
        assert _context({"mode": "interactive"}).max_run_duration() is None

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=0)
    def test_background_runs_get_the_default_cap(self):
        assert _context({"mode": "background"}).max_run_duration() == timedelta(
            seconds=MAX_RUN_DURATION_DEFAULT_SECONDS
        )
        # Default mode (no explicit mode in state) is background.
        assert _context(None).max_run_duration() == timedelta(seconds=MAX_RUN_DURATION_DEFAULT_SECONDS)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=90)
    def test_env_override_applies_to_capped_runs(self):
        assert _context({"mode": "background"}).max_run_duration() == timedelta(seconds=90)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=90)
    def test_env_override_does_not_uncap_interactive(self):
        assert _context({"mode": "interactive"}).max_run_duration() is None
