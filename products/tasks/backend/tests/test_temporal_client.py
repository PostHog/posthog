from unittest.mock import AsyncMock, Mock, patch

from django.test import TestCase, override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import (
    execute_task_processing_workflow,
    execute_task_processing_workflow_async,
    redispatch_orphaned_task_run,
    resume_task_in_cloud_workflow,
)


@override_settings(DEBUG=False)
class TestExecuteTaskProcessingWorkflow(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com")
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _create_run(self, status: TaskRun.Status = TaskRun.Status.QUEUED) -> TaskRun:
        return TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=status,
        )

    def _assert_run_failed(self, run: TaskRun, expected_error: str) -> None:
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertEqual(run.error_message, expected_error)
        self.assertIsNotNone(run.completed_at)

    def _execute_workflow(self, executor: str, run: TaskRun, user_id: int | None) -> None:
        kwargs = {
            "task_id": str(self.task.id),
            "run_id": str(run.id),
            "team_id": self.team.id,
            "user_id": user_id,
        }
        if executor == "sync":
            execute_task_processing_workflow(**kwargs)
            return

        async_to_sync(execute_task_processing_workflow_async)(**kwargs)

    @parameterized.expand([("sync",), ("async",)])
    def test_marks_run_failed_when_temporal_start_fails(self, executor: str) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))

        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        with (
            patch(connect_target, connect_mock),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False),
        ):
            self._execute_workflow(executor, run, self.user.id)

        self._assert_run_failed(run, "Failed to start task workflow: temporal unavailable")

    @parameterized.expand([("sync",), ("async",)])
    def test_does_not_overwrite_run_that_already_started(self, executor: str) -> None:
        run = self._create_run(status=TaskRun.Status.IN_PROGRESS)
        client = Mock()
        client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))

        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        with (
            patch(connect_target, connect_mock),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False),
        ):
            self._execute_workflow(executor, run, self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(run.error_message)
        self.assertIsNone(run.completed_at)

    @parameterized.expand([("sync",), ("async",)])
    def test_captures_sandbox_event_ingest_flag_before_starting_workflow(self, executor: str) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock()

        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        with (
            patch(connect_target, connect_mock),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=True) as flag,
        ):
            self._execute_workflow(executor, run, self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.state["sandbox_event_ingest_enabled"], True)
        flag.assert_called_once_with(
            "tasks-cloud-runs-sandbox-event-ingest",
            distinct_id="process_task_workflow",
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_captures_sandbox_event_ingest_flag_before_resuming_workflow(self) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock()

        with (
            patch("products.tasks.backend.temporal.client.sync_connect", return_value=client),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=True),
        ):
            resume_task_in_cloud_workflow(str(run.id), run.workflow_id)

        run.refresh_from_db()
        self.assertEqual(run.state["sandbox_event_ingest_enabled"], True)

    @parameterized.expand([("sync",), ("async",)])
    def test_captures_sandbox_event_ingest_flag_without_clobbering_concurrent_state(self, executor: str) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock()
        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        def _feature_enabled(*args: object, **kwargs: object) -> bool:
            TaskRun.update_state_atomic(str(run.id), updates={"pending_user_message_ids": ["message-1"]})
            return True

        with (
            patch(connect_target, connect_mock),
            patch(
                "products.tasks.backend.temporal.client.posthoganalytics.feature_enabled",
                side_effect=_feature_enabled,
            ),
        ):
            self._execute_workflow(executor, run, self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.state["pending_user_message_ids"], ["message-1"])
        self.assertEqual(run.state["sandbox_event_ingest_enabled"], True)


@override_settings(DEBUG=False)
class TestRedispatchOrphanedTaskRun(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com")
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _orphaned_run(
        self, pending_dispatch: dict | None = None, run_source: str | None = None, prewarmed: bool = False
    ) -> TaskRun:
        state: dict = {}
        if pending_dispatch is not None:
            state["pending_dispatch"] = pending_dispatch
        if run_source is not None:
            state["run_source"] = run_source
        if prewarmed:
            state["prewarmed"] = True
        return TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.QUEUED, state=state)

    def _run_reconcile(self, run: TaskRun, start_workflow: Mock) -> str:
        client = Mock()
        client.start_workflow = start_workflow
        with (
            patch("products.tasks.backend.temporal.client.sync_connect", return_value=client),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False),
        ):
            return redispatch_orphaned_task_run(str(run.id))

    def test_recovers_orphaned_run_with_persisted_dispatch_params(self) -> None:
        run = self._orphaned_run(pending_dispatch={"create_pr": False, "posthog_mcp_scopes": "full"})
        start_workflow = AsyncMock()

        outcome = self._run_reconcile(run, start_workflow)

        self.assertEqual(outcome, "recovered")
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.error_message)
        # Re-dispatch must be faithful to how the run was created and idempotent (start-if-none).
        _, workflow_input = start_workflow.call_args.args
        self.assertEqual(workflow_input.run_id, str(run.id))
        self.assertEqual(workflow_input.create_pr, False)
        self.assertEqual(workflow_input.posthog_mcp_scopes, "full")
        self.assertEqual(
            start_workflow.call_args.kwargs["id_reuse_policy"],
            WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )

    @parameterized.expand([(None, "full"), ("manual", "full"), ("signal_report", "full")])
    def test_falls_back_to_run_source_scopes_when_dispatch_params_absent(
        self, run_source: str | None, expected_scopes: str
    ) -> None:
        # The app's bootstrap/start path never persists pending_dispatch, so the reconciler must
        # derive mcp scopes from run_source exactly as the original dispatch does — not default to read_only.
        run = self._orphaned_run(run_source=run_source)
        start_workflow = AsyncMock()

        outcome = self._run_reconcile(run, start_workflow)

        self.assertEqual(outcome, "recovered")
        _, workflow_input = start_workflow.call_args.args
        self.assertEqual(workflow_input.posthog_mcp_scopes, expected_scopes)

    def test_does_not_fail_run_when_workflow_already_started(self) -> None:
        run = self._orphaned_run()
        start_workflow = AsyncMock(side_effect=WorkflowAlreadyStartedError(run.workflow_id, "process-task"))

        outcome = self._run_reconcile(run, start_workflow)

        self.assertEqual(outcome, "already_running")
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.error_message)

    def test_does_not_fail_run_on_transient_error(self) -> None:
        run = self._orphaned_run()
        start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))

        outcome = self._run_reconcile(run, start_workflow)

        self.assertEqual(outcome, "error")
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.error_message)
        self.assertIsNone(run.completed_at)

    def test_skips_run_that_left_queue(self) -> None:
        run = self._orphaned_run()
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        start_workflow = AsyncMock()

        outcome = self._run_reconcile(run, start_workflow)

        self.assertEqual(outcome, "left_queue")
        start_workflow.assert_not_called()

    def test_skips_prewarmed_run(self) -> None:
        # Prewarmed runs are owned by the prewarmed reaper (it kills them); re-dispatching one would
        # boot an agent with no user prompt and drop the prewarmed flag, changing boot behaviour.
        run = self._orphaned_run(prewarmed=True)
        start_workflow = AsyncMock()

        outcome = self._run_reconcile(run, start_workflow)

        self.assertEqual(outcome, "skipped_prewarmed")
        start_workflow.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
