import asyncio
from datetime import timedelta
from typing import cast

from unittest.mock import AsyncMock, Mock, patch

from django.conf import settings
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.facade.api import (
    create_and_run_task,
    filter_uncovered_workflow_dispatch_run_ids,
    get_stale_queued_task_run_ids,
    maintain_workflow_dispatch_outbox,
    resume_task_run_in_cloud,
)
from products.tasks.backend.logic.services.workflow_dispatch import (
    RestartSnapshot,
    WorkflowDispatchFlags,
    WorkflowDispatchOptions,
    build_create_payload,
    build_restart_payload,
    create_dispatch,
    dispatch_exceeded_max_age,
    dispatch_task_processing_workflow,
    mark_dead,
    parse_create_payload,
    parse_restart_payload,
    reschedule,
    sample_dispatch_metrics,
)
from products.tasks.backend.management.commands.run_task_workflow_dispatcher import (
    Command,
    _user_can_dispatch,
    restart_attempt_already_started,
)
from products.tasks.backend.metrics import WORKFLOW_DISPATCH_ATTEMPT_TOTAL
from products.tasks.backend.models import Task, TaskRun, TaskWorkflowDispatch
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.process_task.workflow import PendingFollowup


class TestWorkflowDispatchPayload(SimpleTestCase):
    @patch("products.tasks.backend.logic.services.workflow_dispatch.transaction.get_connection")
    @patch("products.tasks.backend.logic.services.workflow_dispatch.TaskWorkflowDispatch.objects")
    def test_duplicate_create_dispatch_reuses_durable_intent(self, objects: Mock, get_connection: Mock) -> None:
        get_connection.return_value.in_atomic_block = True
        task_run = Mock(team_id=1)
        existing = Mock()
        queryset = objects.for_team.return_value
        queryset.get_or_create.return_value = (existing, False)

        result = create_dispatch(task_run, "create", {"version": 1}, "workflow-id")

        self.assertIs(result, existing)
        queryset.get_or_create.assert_called_once()
        queryset.update_or_create.assert_not_called()

    def test_restart_retry_recognizes_workflow_started_by_prior_attempt(self) -> None:
        enqueued_at = django_timezone.now()
        dispatch = Mock(workflow_id="workflow-id", enqueued_at=enqueued_at)
        description = Mock(status=WorkflowExecutionStatus.RUNNING, start_time=enqueued_at + timedelta(seconds=1))
        handle = Mock(describe=AsyncMock(return_value=description))
        client = Mock()
        client.get_workflow_handle.return_value = handle

        self.assertTrue(asyncio.run(restart_attempt_already_started(client, dispatch)))
        handle.describe.assert_awaited_once_with(
            rpc_timeout=timedelta(seconds=settings.TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS)
        )

    def test_create_payload_round_trip_preserves_followup_without_secrets(self) -> None:
        options = WorkflowDispatchOptions(
            user_id=42,
            create_pr=False,
            posthog_mcp_scopes="full",
            slack_thread_context={"channel_id": "C1"},
            prewarmed=True,
            skip_user_check=True,
            initial_message=PendingFollowup(
                message="continue",
                artifact_ids=["artifact-1"],
                actor_user_id=42,
                message_id="message-1",
            ),
        )

        payload = build_create_payload(options)

        self.assertEqual(parse_create_payload(payload), options)
        self.assertNotIn("imported_mcp_servers", payload)

    def test_unknown_payload_version_is_rejected(self) -> None:
        payload = build_create_payload(WorkflowDispatchOptions())
        payload["version"] = 2

        with self.assertRaisesRegex(ValueError, "Unsupported workflow dispatch payload version"):
            parse_create_payload(payload)

    @patch("products.tasks.backend.logic.services.workflow_dispatch.TaskWorkflowDispatch.objects")
    @patch("products.tasks.backend.logic.services.workflow_dispatch.random.uniform", return_value=1.0)
    def test_reschedule_clamps_exponential_backoff(self, uniform: Mock, objects: Mock) -> None:
        objects.unscoped.return_value.get.return_value.attempt_count = 10_000

        reschedule("dispatch-id", "instance-id", "error")

        uniform.assert_called_once_with(1.0, 256.0)

    def test_restart_payload_round_trip_preserves_compensation_snapshot(self) -> None:
        snapshot = RestartSnapshot(
            status="failed",
            environment="local",
            completed_at="2026-08-14T10:00:00+00:00",
            queued_at=None,
            state={"snapshot_external_id": "snapshot-1"},
        )

        payload = build_restart_payload(42, snapshot)

        self.assertEqual(parse_restart_payload(payload), (42, snapshot))


class TestWorkflowDispatchPersistence(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=organization, name="Test Team")
        user = User.objects.create(email="test@example.com")
        task = Task.objects.create(
            team=self.team,
            created_by=user,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

    @patch("products.tasks.backend.temporal.client._terminalize_unstarted_task_run")
    def test_malformed_restart_payload_is_terminalized_after_marking_dispatch_dead(self, terminalize: Mock) -> None:
        dispatch = TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=self.task_run,
            workflow_id=self.task_run.workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.RESTART,
            payload={"version": 999},
            status=TaskWorkflowDispatch.Status.CLAIMED,
            claimed_by="dispatcher-1",
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(mark_dead(dispatch.id, "dispatcher-1", "invalid restart payload"), 1)

        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, TaskWorkflowDispatch.Status.DEAD)
        terminalize.assert_called_once_with(str(self.task_run.id), "invalid restart payload")

    @patch("products.tasks.backend.feature_flags.is_workflow_dispatch_restart_enabled")
    def test_restart_flag_is_evaluated_before_locking_run(self, restart_enabled: Mock) -> None:
        baseline_atomic_depth = len(transaction.get_connection().atomic_blocks)

        def assert_outside_transaction(*_args: object) -> bool:
            self.assertEqual(len(transaction.get_connection().atomic_blocks), baseline_atomic_depth)
            return True

        restart_enabled.side_effect = assert_outside_transaction

        outcome, _, _ = resume_task_run_in_cloud(self.task_run.id, self.task_run.task_id, self.team.id, None)

        self.assertEqual(outcome, "already_active")

    def test_reenqueuing_restart_resets_dispatch_age(self) -> None:
        snapshot = RestartSnapshot(
            status=TaskRun.Status.FAILED,
            environment=TaskRun.Environment.LOCAL,
            completed_at=None,
            queued_at=None,
            state={},
        )
        first_enqueued_at = django_timezone.now() - timedelta(days=1)
        with (
            patch(
                "products.tasks.backend.logic.services.workflow_dispatch.django_timezone.now",
                return_value=first_enqueued_at,
            ),
            transaction.atomic(),
        ):
            dispatch = create_dispatch(
                self.task_run,
                TaskWorkflowDispatch.Kind.RESTART,
                build_restart_payload(None, snapshot),
                self.task_run.workflow_id,
            )
        TaskWorkflowDispatch.objects.unscoped().filter(id=dispatch.id).update(created_at=first_enqueued_at)

        reenqueued_at = django_timezone.now()
        with (
            patch(
                "products.tasks.backend.logic.services.workflow_dispatch.django_timezone.now",
                return_value=reenqueued_at,
            ),
            transaction.atomic(),
        ):
            create_dispatch(
                self.task_run,
                TaskWorkflowDispatch.Kind.RESTART,
                build_restart_payload(None, snapshot),
                self.task_run.workflow_id,
            )

        dispatch.refresh_from_db()
        self.assertEqual(dispatch.enqueued_at, reenqueued_at)
        self.assertFalse(dispatch_exceeded_max_age(dispatch, 6 * 60 * 60, now=reenqueued_at))

    def test_oldest_ready_age_uses_latest_enqueue_time(self) -> None:
        now = django_timezone.now()
        snapshot = RestartSnapshot(
            status=TaskRun.Status.FAILED,
            environment=TaskRun.Environment.LOCAL,
            completed_at=None,
            queued_at=None,
            state={},
        )
        with transaction.atomic():
            dispatch = create_dispatch(
                self.task_run,
                TaskWorkflowDispatch.Kind.RESTART,
                build_restart_payload(None, snapshot),
                self.task_run.workflow_id,
            )
        TaskWorkflowDispatch.objects.unscoped().filter(id=dispatch.id).update(
            created_at=now - timedelta(days=1),
            enqueued_at=now - timedelta(minutes=5),
            next_attempt_at=now - timedelta(minutes=5),
        )

        with (
            patch("products.tasks.backend.logic.services.workflow_dispatch.django_timezone.now", return_value=now),
            patch(
                "products.tasks.backend.logic.services.workflow_dispatch.WORKFLOW_DISPATCH_OLDEST_READY_AGE_SECONDS.set"
            ) as set_oldest_age,
        ):
            sample_dispatch_metrics()

        set_oldest_age.assert_called_once_with(300.0)

    @patch("products.tasks.backend.metrics.WORKFLOW_DISPATCH_MISSING_INTENT_TOTAL.inc")
    @patch("products.tasks.backend.facade.api.is_workflow_dispatch_shadow_enabled", return_value=False)
    def test_missing_intent_metric_stays_quiet_before_shadow_rollout(
        self, _shadow_enabled: Mock, increment_missing_intent: Mock
    ) -> None:
        uncovered = filter_uncovered_workflow_dispatch_run_ids([self.task_run.id])

        self.assertEqual(uncovered, [self.task_run.id])
        increment_missing_intent.assert_not_called()

    @patch("products.tasks.backend.metrics.WORKFLOW_DISPATCH_MISSING_INTENT_TOTAL.inc")
    @patch("products.tasks.backend.facade.api.is_workflow_dispatch_shadow_enabled", return_value=True)
    def test_missing_intent_counts_bare_runs_but_not_restart_rollout_gaps(
        self, _shadow_enabled: Mock, increment_missing_intent: Mock
    ) -> None:
        resumed_run = TaskRun.objects.create(
            task=self.task_run.task, team=self.team, status=TaskRun.Status.QUEUED, state={"same_run_resume": True}
        )

        uncovered = filter_uncovered_workflow_dispatch_run_ids([self.task_run.id, resumed_run.id])

        self.assertEqual(uncovered, [self.task_run.id, resumed_run.id])
        increment_missing_intent.assert_called_once()

    def test_deferred_start_create_and_run_persists_dispatch_marker(self) -> None:
        creator_id = self.task_run.task.created_by_id
        assert creator_id is not None
        created = create_and_run_task(
            team=self.team,
            title="Deferred start",
            description="Created without starting the workflow",
            origin_product=Task.OriginProduct.SLACK,
            user_id=creator_id,
            create_pr=False,
            mode="interactive",
            start_workflow=False,
            posthog_mcp_scopes="full",
        )

        assert created.latest_run is not None
        run = TaskRun.objects.get(id=created.latest_run.id)
        marker = run.state["pending_dispatch"]
        self.assertFalse(marker["create_pr"])
        self.assertEqual(marker["posthog_mcp_scopes"], "full")

    @parameterized.expand(
        [
            ("already_started_keeps_run_alive", WorkflowAlreadyStartedError("wf", "process-task"), False, "queued"),
            ("durable_dispatch_leaves_retry_to_dispatcher", RuntimeError("temporal down"), True, "queued"),
            ("no_durable_dispatch_terminalizes", RuntimeError("temporal down"), False, "failed"),
        ]
    )
    @patch("products.tasks.backend.temporal.client.sync_connect")
    def test_sync_start_failure_only_terminalizes_without_durable_dispatch(
        self, _name: str, error: Exception, durable_dispatch: bool, expected_status: str, connect: Mock
    ) -> None:
        connect.side_effect = error

        with self.captureOnCommitCallbacks(execute=True):
            execute_task_processing_workflow(
                task_id=str(self.task_run.task_id),
                run_id=str(self.task_run.id),
                team_id=self.team.id,
                durable_dispatch=durable_dispatch,
            )

        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.status, expected_status)

    def test_dispatch_facade_normalizes_slack_context_into_shadow_row(self) -> None:
        class Context:
            def to_dict(self) -> dict:
                return {"channel": "C1", "thread_ts": "123.45"}

        with (
            patch(
                "products.tasks.backend.logic.services.workflow_dispatch.evaluate_workflow_dispatch_flags",
                return_value=WorkflowDispatchFlags(shadow_enabled=True, async_enabled=False),
            ),
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow") as start,
            self.captureOnCommitCallbacks(execute=True),
        ):
            dispatch_task_processing_workflow(
                task_id=str(self.task_run.task_id),
                run_id=str(self.task_run.id),
                team_id=self.team.id,
                user_id=self.task_run.task.created_by_id,
                slack_thread_context=Context(),
                posthog_mcp_scopes="full",
            )

        row = TaskWorkflowDispatch.objects.unscoped().get(task_run=self.task_run)
        self.assertEqual(row.payload["slack_thread_context"], {"channel": "C1", "thread_ts": "123.45"})
        start.assert_called_once()

    def test_reconciler_excludes_covered_runs_at_any_age_unlike_the_killer_view(self) -> None:
        orphan_run = TaskRun.objects.create(task=self.task_run.task, team=self.team, status=TaskRun.Status.QUEUED)
        TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=self.task_run,
            workflow_id=self.task_run.workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
            payload={"version": 1},
            status=TaskWorkflowDispatch.Status.PENDING,
        )
        # Age the covered run's dispatch past the killer's coverage window, and both runs past staleness.
        TaskWorkflowDispatch.objects.unscoped().filter(task_run=self.task_run).update(
            enqueued_at=django_timezone.now()
            - timedelta(seconds=settings.TASKS_DISPATCHER_MAX_DISPATCH_AGE_SECONDS + 3600)
        )
        TaskRun.objects.filter(id__in=[self.task_run.id, orphan_run.id]).update(
            updated_at=django_timezone.now() - timedelta(hours=1)
        )

        reconciler_view = get_stale_queued_task_run_ids(
            timedelta(minutes=5), 500, environment=TaskRun.Environment.CLOUD, exclude_covered_dispatches=True
        )
        killer_view = get_stale_queued_task_run_ids(timedelta(minutes=5), 500, environment=TaskRun.Environment.CLOUD)

        self.assertEqual(reconciler_view, [orphan_run.id])
        self.assertIn(self.task_run.id, killer_view)

    def test_outbox_maintenance_prunes_dead_rows_only_after_retention(self) -> None:
        second_run = TaskRun.objects.create(task=self.task_run.task, team=self.team, status=TaskRun.Status.QUEUED)
        old_dead = TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=self.task_run,
            workflow_id=self.task_run.workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
            payload={"version": 1},
            status=TaskWorkflowDispatch.Status.DEAD,
        )
        fresh_dead = TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=second_run,
            workflow_id=second_run.workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
            payload={"version": 1},
            status=TaskWorkflowDispatch.Status.DEAD,
        )
        TaskWorkflowDispatch.objects.unscoped().filter(id=old_dead.id).update(
            updated_at=django_timezone.now() - timedelta(days=31)
        )

        maintain_workflow_dispatch_outbox()

        remaining = set(TaskWorkflowDispatch.objects.unscoped().values_list("id", flat=True))
        self.assertEqual(remaining, {fresh_dead.id})


class TestWorkflowDispatchPermissions(SimpleTestCase):
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.UserPermissions")
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.User.objects")
    def test_user_requires_current_effective_team_access(self, users: Mock, permissions: Mock) -> None:
        user = users.filter.return_value.first.return_value
        permissions.return_value.current_team.effective_membership_level = None
        run = Mock(task=Mock(team=Mock(), created_by_id=99))

        self.assertFalse(_user_can_dispatch(run, WorkflowDispatchOptions(user_id=42)))
        users.filter.assert_called_once_with(id=42, is_active=True)
        permissions.assert_called_once_with(user=user, team=run.task.team)

    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.User.objects")
    def test_trusted_system_dispatch_skips_user_lookup(self, users: Mock) -> None:
        run = Mock(task=Mock(team=Mock()))

        self.assertTrue(_user_can_dispatch(run, WorkflowDispatchOptions(skip_user_check=True)))
        users.filter.assert_not_called()


class TestDispatcherCompletionCallback(SimpleTestCase):
    @parameterized.expand(
        [
            ("failure", RuntimeError("connection reset"), 1),
            ("success", None, 0),
        ]
    )
    def test_completion_records_failure_outcome_only_on_exception(
        self, name: str, exception: Exception | None, expected_delta: int
    ) -> None:
        task_mock = Mock()
        task_mock.cancelled.return_value = False
        task_mock.exception.return_value = exception
        task = cast(asyncio.Task[None], task_mock)
        dispatch = Mock(id=f"dispatch-{name}", task_run_id="run-1", dispatch_kind="create")
        in_flight = {task}
        in_flight_ids = {dispatch.id}

        def failed_total() -> float:
            return WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind="create", outcome="failed")._value.get()

        before = failed_total()
        Command._on_dispatch_done(in_flight, in_flight_ids, dispatch, task)

        self.assertEqual(failed_total() - before, expected_delta)
        self.assertNotIn(task, in_flight)
        self.assertNotIn(dispatch.id, in_flight_ids)
