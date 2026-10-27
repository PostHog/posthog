import uuid
from dataclasses import replace

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport
from products.tasks.backend.facade.profiles import profile_for_task
from products.tasks.backend.management.commands.backfill_task_profiles import backfill_task_profiles
from products.tasks.backend.models import Task, TaskRun


class TestBackfillTaskProfiles(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")

    def _task(self, origin_product: str, *, internal: bool = False, ai_stages: tuple[str, ...] = (), **fields) -> Task:
        task = Task.objects.create(
            team=self.team, title="Task", description="d", origin_product=origin_product, internal=internal, **fields
        )
        for stage in ai_stages:
            TaskRun.objects.create(task=task, team=self.team, state={"ai_stage": stage})
        return task

    @parameterized.expand(
        [
            ("user", "user_created", False, None, (), "user"),
            ("inbox", "signal_report", False, None, (), "signals.inbox"),
            ("research_stage", "signal_report", True, None, ("research",), "signals.research"),
            ("repo_selection_stage", "signal_report", True, None, ("repo_selection",), "signals.repo_selection"),
            ("custom_agent_stage", "signal_report", True, None, ("custom_agent",), "signals.custom_agent"),
            ("other_stage", "signal_report", True, None, ("implementation",), "signals.implementation"),
            ("no_runs", "signal_report", True, None, (), "signals.implementation"),
            ("newest_stage_wins", "signal_report", True, None, ("research", "custom_agent"), "signals.custom_agent"),
            ("imported_conversation", "posthog_ai", False, "phai-conversation:abc", (), "posthog_ai.imported"),
            ("live_conversation", "posthog_ai", False, "chat:abc", (), "posthog_ai"),
            ("imported_internal", "posthog_ai", True, "phai-conversation:abc", (), "posthog_ai.imported_internal"),
        ]
    )
    def test_backfilled_profile_matches_origin_and_newest_stage_and_keeps_legacy_behavior(
        self,
        _name: str,
        origin_product: str,
        internal: bool,
        origin_key: str | None,
        ai_stages: tuple[str, ...],
        expected_profile: str,
    ) -> None:
        task = self._task(origin_product, internal=internal, origin_key=origin_key, ai_stages=ai_stages)
        legacy = profile_for_task(task)

        backfill_task_profiles()

        task.refresh_from_db()
        backfilled = profile_for_task(task)
        assert task.profile == expected_profile
        assert replace(backfilled, key=legacy.key, public=legacy.public) == legacy

    def test_fills_source_and_idempotency_fields_and_leaves_profiled_rows_alone(self) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        hog_flow_id = uuid.uuid4()
        from_report = self._task("signal_report", signal_report=report, origin_key="report:1")
        from_workflow = self._task("workflow", hog_flow_id=hog_flow_id, origin_key="workflow:1")
        plain = self._task("user_created")
        profiled = self._task("user_created", profile="loop", origin_key="keep:1")

        assert backfill_task_profiles(dry_run=True) == 3
        from_report.refresh_from_db()
        assert from_report.profile is None

        assert backfill_task_profiles(batch_size=2) == 3
        assert backfill_task_profiles() == 0

        for task in (from_report, from_workflow, plain, profiled):
            task.refresh_from_db()
        assert (from_report.source_kind, from_report.source_id, from_report.idempotency_key) == (
            "signal_report",
            str(report.id),
            "report:1",
        )
        assert (from_workflow.source_kind, from_workflow.source_id, from_workflow.idempotency_key) == (
            "hog_flow",
            str(hog_flow_id),
            "workflow:1",
        )
        assert (plain.source_kind, plain.source_id, plain.idempotency_key) == (None, None, None)
        assert (profiled.profile, profiled.source_kind, profiled.idempotency_key) == ("loop", None, None)
