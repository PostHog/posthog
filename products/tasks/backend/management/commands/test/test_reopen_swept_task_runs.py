from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from typing import Any

from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import ReopenedSweptRunsRow
from products.tasks.backend.models import ENDED_BY_STALE_SWEEP_STATE_KEY, Task, TaskRun
from products.tasks.backend.task_profiles import USER

FLAG_PAYLOAD = "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload"
WORKFLOW_RUNNING = SimpleNamespace(status=WorkflowExecutionStatus.RUNNING)
WORKFLOW_NOT_FOUND = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")
TEMPORAL_DOWN = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
SWEPT = {ENDED_BY_STALE_SWEEP_STATE_KEY: "heartbeat"}
REOPENED_ONE = [ReopenedSweptRunsRow(outcome="reopened", count=1)]


class TestReopenSweptTaskRuns(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        connect = patch("posthog.temporal.common.client.sync_connect").start()
        self.addCleanup(patch.stopall)
        self.describe_workflow = AsyncMock(return_value=WORKFLOW_RUNNING)
        connect.return_value.get_workflow_handle.return_value.describe = self.describe_workflow

    def _task(self, *, team: Team | None = None, profile: str | None = USER.key) -> Task:
        return Task.objects.create(
            team=team or self.team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            profile=profile,
        )

    def _failed_run(
        self,
        *,
        team: Team | None = None,
        profile: str | None = USER.key,
        state: dict[str, Any] | None = None,
        ended_ago: timedelta = timedelta(minutes=30),
    ) -> TaskRun:
        ended_at = timezone.now() - ended_ago
        run = TaskRun.objects.create(
            task=self._task(team=team, profile=profile),
            team=team or self.team,
            status=TaskRun.Status.FAILED,
            environment=TaskRun.Environment.CLOUD,
            error_message="This run stopped responding, so it was ended.",
            completed_at=ended_at,
            state=dict(SWEPT) if state is None else state,
        )
        TaskRun.objects.filter(id=run.id).update(updated_at=ended_at)
        return run

    @parameterized.expand([("of_a_profile", USER.key), ("of_a_task_without_a_profile", None)])
    def test_reopens_a_run_the_sweep_ended(self, _name: str, profile: str | None) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            run = self._failed_run(profile=profile)

        with patch(FLAG_PAYLOAD, return_value={}), self.captureOnCommitCallbacks(execute=True):
            rows = tasks_facade.reopen_swept_task_runs(profile=profile or "none")

        run.refresh_from_db()
        run.task.refresh_from_db()
        self.assertEqual(rows, REOPENED_ONE)
        self.assertEqual((run.status, run.error_message, run.completed_at), (TaskRun.Status.IN_PROGRESS, None, None))
        self.assertEqual(run.state, {})
        self.assertEqual(run.task.status, Task.Status.RUNNING)

    @parameterized.expand(
        [
            ("of_a_profile_that_still_enforces", {"flag": {"return_value": {USER.key: "enforce"}}}, "still_enforced"),
            ("of_a_profile_whose_mode_is_unknown", {"flag": {"side_effect": RuntimeError("down")}}, "mode_unknown"),
            ("whose_workflow_is_gone", {"workflow": WORKFLOW_NOT_FOUND}, "workflow_gone"),
            ("whose_task_has_a_newer_run", {"newer_run": True}, "moved_on"),
            ("that_only_carries_the_sweep_message", {"run": {"state": {}}}, None),
            ("of_another_profile", {"run": {"profile": "other"}}, None),
            ("ended_before_the_window", {"run": {"ended_ago": timedelta(hours=25)}}, None),
        ]
    )
    def test_leaves_a_run_failed(self, _name: str, scenario: dict[str, Any], outcome: str | None) -> None:
        run = self._failed_run(**scenario.get("run", {}))
        if scenario.get("newer_run"):
            TaskRun.objects.create(task=run.task, team=self.team, status=TaskRun.Status.COMPLETED)
        if "workflow" in scenario:
            self.describe_workflow.side_effect = scenario["workflow"]

        with patch(FLAG_PAYLOAD, **scenario.get("flag", {"return_value": {}})):
            rows = tasks_facade.reopen_swept_task_runs(profile=USER.key)

        run.refresh_from_db()
        self.assertEqual(rows, [ReopenedSweptRunsRow(outcome=outcome, count=1)] if outcome else [])
        self.assertEqual(run.status, TaskRun.Status.FAILED)

    def test_leaves_a_run_that_was_resumed_after_it_was_listed(self) -> None:
        run = self._failed_run()

        def mode_while_the_run_is_resumed(*args: Any, **kwargs: Any) -> dict[str, str]:
            TaskRun.objects.filter(id=run.id).update(status=TaskRun.Status.QUEUED, state={})
            return {}

        with patch(FLAG_PAYLOAD, side_effect=mode_while_the_run_is_resumed):
            rows = tasks_facade.reopen_swept_task_runs(profile=USER.key)

        run.refresh_from_db()
        self.assertEqual(rows, [ReopenedSweptRunsRow(outcome="moved_on", count=1)])
        self.assertEqual(run.status, TaskRun.Status.QUEUED)

    def test_reopens_a_run_whose_workflow_is_gone_when_the_check_is_skipped(self) -> None:
        run = self._failed_run()
        self.describe_workflow.side_effect = WORKFLOW_NOT_FOUND

        with patch(FLAG_PAYLOAD, return_value={}):
            rows = tasks_facade.reopen_swept_task_runs(profile=USER.key, check_workflows=False)

        run.refresh_from_db()
        self.assertEqual((rows, run.status), (REOPENED_ONE, TaskRun.Status.IN_PROGRESS))

    def test_stops_without_reopening_when_temporal_is_unreachable(self) -> None:
        runs = [self._failed_run() for _ in range(2)]
        self.describe_workflow.side_effect = TEMPORAL_DOWN

        with patch(FLAG_PAYLOAD, return_value={}), self.assertRaises(RPCError):
            tasks_facade.reopen_swept_task_runs(profile=USER.key)

        statuses = set(TaskRun.objects.filter(id__in=[run.id for run in runs]).values_list("status", flat=True))
        self.assertEqual(statuses, {TaskRun.Status.FAILED})

    def test_only_reopens_the_given_team(self) -> None:
        other_team = Team.objects.create(organization=self.team.organization, name="Other")
        run = self._failed_run()
        other = self._failed_run(team=other_team)

        with patch(FLAG_PAYLOAD, return_value={}):
            rows = tasks_facade.reopen_swept_task_runs(profile=USER.key, team_id=self.team.pk)

        run.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(rows, REOPENED_ONE)
        self.assertEqual((run.status, other.status), (TaskRun.Status.IN_PROGRESS, TaskRun.Status.FAILED))

    def test_dry_run_counts_without_writing(self) -> None:
        runs = [self._failed_run() for _ in range(2)]
        self.describe_workflow.side_effect = [WORKFLOW_RUNNING, WORKFLOW_NOT_FOUND]

        stdout = StringIO()
        with patch(FLAG_PAYLOAD, return_value={}):
            call_command("reopen_swept_task_runs", "--profile", USER.key, "--dry-run", stdout=stdout)

        statuses = set(TaskRun.objects.filter(id__in=[run.id for run in runs]).values_list("status", flat=True))
        self.assertEqual(
            stdout.getvalue().splitlines(),
            ["Skipped 1 runs: the workflow is no longer running", "Would reopen 1 runs in all"],
        )
        self.assertEqual(statuses, {TaskRun.Status.FAILED})

    @parameterized.expand(
        [
            ("by_the_heartbeat_rule", timedelta(hours=2), WORKFLOW_NOT_FOUND),
            ("by_the_day_rule", timedelta(hours=25), None),
        ]
    )
    def test_reopens_a_run_the_real_sweep_ended(
        self, _name: str, last_written_ago: timedelta, workflow_at_sweep: Exception | None
    ) -> None:
        last_written = timezone.now() - last_written_ago
        run = TaskRun.objects.create(
            task=self._task(),
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            environment=TaskRun.Environment.CLOUD,
            created_at=last_written,
            last_heartbeat_at=last_written,
            agent_status=TaskRun.AgentStatus.READY,
            state={"inactivity_timeout_seconds": 600},
        )
        TaskRun.objects.filter(id=run.id).update(updated_at=last_written)
        self.describe_workflow.side_effect = workflow_at_sweep
        with patch(FLAG_PAYLOAD, return_value={USER.key: "enforce"}):
            tasks_facade.sweep_stale_live_task_runs()
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.describe_workflow.side_effect = None

        with patch(FLAG_PAYLOAD, return_value={USER.key: "off"}):
            rows = tasks_facade.reopen_swept_task_runs(profile=USER.key)

        run.refresh_from_db()
        self.assertEqual((rows, run.status), (REOPENED_ONE, TaskRun.Status.IN_PROGRESS))
        self.assertEqual(run.state, {"inactivity_timeout_seconds": 600})
