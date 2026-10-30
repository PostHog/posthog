from datetime import timedelta

from django.test import override_settings

from parameterized import parameterized

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.constants import MAX_INACTIVITY_TIMEOUT_SECONDS, resolve_max_run_duration
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

DEFAULT_CAP_SECONDS = 3 * 60 * 60


def _context(
    state: dict | None,
    *,
    origin_product: str | None = Task.OriginProduct.WORKFLOW.value,
    profile_key: str | None = None,
    profile_max_wake_minutes: int | None = None,
) -> TaskProcessingContext:
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
        origin_product=origin_product,
        profile_key=profile_key,
        profile_max_wake_minutes=profile_max_wake_minutes,
    )


class TestMaxRunDuration:
    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=DEFAULT_CAP_SECONDS)
    def test_interactive_sessions_are_uncapped(self):
        # A human may legitimately keep an interactive session open for hours; capping it
        # would kill a live session mid-use.
        assert _context({"mode": "interactive"}).max_run_duration() is None

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=DEFAULT_CAP_SECONDS)
    def test_autonomous_background_runs_get_the_default_cap(self):
        assert _context({"mode": "background"}).max_run_duration() == timedelta(seconds=DEFAULT_CAP_SECONDS)
        # Default mode (no explicit mode in state) is background.
        assert _context(None).max_run_duration() == timedelta(seconds=DEFAULT_CAP_SECONDS)

    @parameterized.expand(
        [
            ("explicit_user_created", Task.OriginProduct.USER_CREATED.value),
            ("missing_origin", None),
        ]
    )
    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=DEFAULT_CAP_SECONDS)
    def test_user_created_background_runs_are_uncapped(self, _name: str, origin_product: str | None):
        assert _context({"mode": "background"}, origin_product=origin_product).max_run_duration() is None

    @parameterized.expand(
        [
            ("profile_cap", "background", Task.OriginProduct.WORKFLOW.value, 120, DEFAULT_CAP_SECONDS, 120),
            (
                "profile_cap_on_user_origin",
                "background",
                Task.OriginProduct.USER_CREATED.value,
                120,
                DEFAULT_CAP_SECONDS,
                120,
            ),
            ("profile_without_cap", "background", Task.OriginProduct.WORKFLOW.value, None, DEFAULT_CAP_SECONDS, None),
            (
                "interactive_profile_task",
                "interactive",
                Task.OriginProduct.WORKFLOW.value,
                120,
                DEFAULT_CAP_SECONDS,
                None,
            ),
            ("setting_disables_profile_cap", "background", Task.OriginProduct.WORKFLOW.value, 120, 0, None),
            ("setting_below_profile_cap", "background", Task.OriginProduct.WORKFLOW.value, 120, 3600, 60),
        ]
    )
    def test_profile_sets_the_cap(
        self,
        _name: str,
        mode: str,
        origin_product: str,
        max_wake_minutes: int | None,
        setting_seconds: int,
        expected_minutes: int | None,
    ):
        context = _context(
            {"mode": mode},
            origin_product=origin_product,
            profile_key="test.profile",
            profile_max_wake_minutes=max_wake_minutes,
        )

        with override_settings(TASKS_MAX_RUN_DURATION_SECONDS=setting_seconds):
            result = context.max_run_duration()

        assert result == (None if expected_minutes is None else timedelta(minutes=expected_minutes))

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=90)
    def test_setting_override_applies_to_capped_runs(self):
        assert resolve_max_run_duration() == timedelta(seconds=90)
        assert _context({"mode": "background"}).max_run_duration() == timedelta(seconds=90)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=90)
    def test_setting_override_does_not_cap_interactive(self):
        assert _context({"mode": "interactive"}).max_run_duration() is None

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=DEFAULT_CAP_SECONDS)
    def test_cap_clears_the_longest_inactivity_grace(self):
        # The cap must sit above the largest legitimate idle window (2h per-task max),
        # or it would fire before the inactivity timer on healthy long runs.
        cap = resolve_max_run_duration()
        assert cap is not None
        assert cap > timedelta(seconds=MAX_INACTIVITY_TIMEOUT_SECONDS)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=0)
    def test_zero_disables_the_cap_rather_than_capping_at_zero(self):
        # 0 is the "unset" convention TASKS_INACTIVITY_TIMEOUT_SECONDS already uses. Reading it
        # as a zero-second cap would terminalize every non-interactive run on its first loop
        # iteration, which is the opposite of what an operator disabling the cap wants.
        assert resolve_max_run_duration() is None
        assert _context({"mode": "background"}).max_run_duration() is None

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=-1)
    def test_negative_disables_the_cap(self):
        assert resolve_max_run_duration() is None

    def test_interactive_signals_cap_applies_when_the_activity_resolved_one(self):
        # User-started signals runs (unbilled inference) get a finite ceiling via the field the
        # activity resolves; other interactive runs keep the exemption. None is also what
        # pre-existing run histories decode, so replays schedule no timer.
        context = _context({"mode": "interactive"}, origin_product=Task.OriginProduct.SIGNAL_REPORT.value)
        assert context.max_run_duration() is None
        context.interactive_max_run_duration_seconds = 6 * 60 * 60
        assert context.max_run_duration() == timedelta(seconds=6 * 60 * 60)
