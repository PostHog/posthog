from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team, User

from products.tasks.backend.models import Task, TaskRun

MODULE = "products.tasks.backend.team_deletion"


def _cancellable_client() -> tuple[MagicMock, AsyncMock]:
    cancel = AsyncMock()
    handle = MagicMock()
    handle.cancel = cancel
    client = MagicMock()
    client.get_workflow_handle.return_value = handle
    return client, cancel


class TestCancelTaskWorkflowsOnTeamDelete(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(
            email="tasks-team-delete@example.com", first_name="Owner", password="password"
        )

    def _run(self, status: str) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Fix the flake",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=status)

    def test_deleting_a_team_stops_only_its_live_run_workflows(self):
        # The rows are collected by CASCADE without ever calling TaskRun.delete(), so the
        # workflow IDs have to be captured in pre_delete or they are unrecoverable.
        live = self._run(TaskRun.Status.IN_PROGRESS)
        queued = self._run(TaskRun.Status.QUEUED)
        self._run(TaskRun.Status.COMPLETED)
        team_id = self.team.pk

        with patch(f"{MODULE}.cancel_task_workflows") as cancel_workflows:
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        cancel_workflows.assert_called_once()
        called_team_id, workflows = cancel_workflows.call_args.args
        self.assertEqual(called_team_id, team_id)
        self.assertEqual(
            dict(workflows),
            {str(live.id): live.workflow_id, str(queued.id): queued.workflow_id},
        )

    def test_no_temporal_call_when_the_team_has_no_live_runs(self):
        self._run(TaskRun.Status.CANCELLED)

        with patch(f"{MODULE}.cancel_task_workflows") as cancel_workflows:
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        cancel_workflows.assert_not_called()

    def test_both_the_orchestrator_and_its_sandbox_workflow_are_cancelled(self):
        # execute_sandbox is started as an independent top-level execution, so cancelling the
        # orchestrator alone would leave the workflow holding the Modal sandbox running.
        run = self._run(TaskRun.Status.IN_PROGRESS)
        client, cancel = _cancellable_client()

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        self.assertEqual(
            [call.args[0] for call in client.get_workflow_handle.call_args_list],
            [run.workflow_id, f"{run.workflow_id}-sandbox"],
        )
        # Cancel rather than terminate: only the workflow's own cancellation path reaps the
        # sandbox, and the rows that would let anything else reap it are already gone.
        self.assertEqual(cancel.await_count, 2)
        # Every call is bounded, so an unreachable frontend cannot burn the caller's budget.
        self.assertTrue(all(call.kwargs.get("rpc_timeout") for call in cancel.await_args_list))

    def test_a_missing_workflow_is_not_reported_as_a_failure(self):
        # NOT_FOUND is the normal outcome for a run that never started a sandbox workflow.
        self._run(TaskRun.Status.IN_PROGRESS)
        client, cancel = _cancellable_client()
        cancel.side_effect = RPCError("no such workflow", RPCStatusCode.NOT_FOUND, b"")

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            with self.assertNoLogs(MODULE, level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    self.team.delete()

        self.assertEqual(cancel.await_count, 2)

    def test_temporal_failures_never_block_the_delete(self):
        run = self._run(TaskRun.Status.IN_PROGRESS)
        team_id = self.team.pk
        client = MagicMock()
        client.get_workflow_handle.side_effect = RuntimeError("temporal unreachable")

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            with self.captureOnCommitCallbacks(execute=True):
                self.team.delete()

        self.assertEqual(
            [call.args[0] for call in client.get_workflow_handle.call_args_list],
            [run.workflow_id, f"{run.workflow_id}-sandbox"],
        )
        self.assertFalse(Team.objects.filter(pk=team_id).exists())
        self.assertFalse(TaskRun.objects.filter(id=run.id).exists())
