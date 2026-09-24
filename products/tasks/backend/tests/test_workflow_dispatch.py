import asyncio
import threading
from datetime import timedelta
from typing import cast

from unittest.mock import AsyncMock, Mock, patch

from django.conf import settings
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.user import User

from products.tasks.backend.facade.api import (
    create_and_run_task,
    filter_uncovered_workflow_dispatch_run_ids,
    get_stale_queued_task_run_ids,
    maintain_workflow_dispatch_outbox,
    resume_task_run_in_cloud,
)
from products.tasks.backend.logic.services.code_usage_gate import CodeUsageStatus
from products.tasks.backend.logic.services.workflow_dispatch import (
    RestartSnapshot,
    WorkflowDispatchFlags,
    WorkflowDispatchOptions,
    build_create_payload,
    build_restart_payload,
    claim_dispatches,
    create_dispatch,
    dispatch_exceeded_max_age,
    dispatch_task_processing_workflow,
    mark_dead,
    materialize_due_scheduled_task_runs,
    parse_create_payload,
    parse_restart_payload,
    reschedule,
    sample_dispatch_metrics,
)
from products.tasks.backend.management.commands.run_task_workflow_dispatcher import (
    Command,
    _scheduled_run_usage_error,
    _user_can_dispatch,
    dispatch_attempt_already_started,
)
from products.tasks.backend.metrics import WORKFLOW_DISPATCH_ATTEMPT_TOTAL
from products.tasks.backend.models import Channel, ChannelMembership, Task, TaskRun, TaskWorkflowDispatch
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
        dispatch = Mock(
            workflow_id="workflow-id", enqueued_at=enqueued_at, dispatch_kind=TaskWorkflowDispatch.Kind.RESTART
        )
        description = Mock(status=WorkflowExecutionStatus.RUNNING, start_time=enqueued_at + timedelta(seconds=1))
        handle = Mock(describe=AsyncMock(return_value=description))
        client = Mock()
        client.get_workflow_handle.return_value = handle

        self.assertTrue(asyncio.run(dispatch_attempt_already_started(client, dispatch)))
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

    @parameterized.expand(
        [
            ("scheduled_over_limit", True, True, False),
            ("scheduled_allowed", True, False, False),
            ("scheduled_deactivated", True, False, True),
            ("immediate_unchanged", False, True, False),
        ]
    )
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher._capture_run_feature_flags")
    @patch("products.tasks.backend.logic.services.code_usage_gate.organization_deactivated")
    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_dispatch_rechecks_scheduled_usage(
        self,
        name: str,
        scheduled: bool,
        limited: bool,
        deactivated: bool,
        get_usage: Mock,
        organization_deactivated: Mock,
        capture_flags: Mock,
    ) -> None:
        user = self.task_run.task.created_by
        assert user is not None
        OrganizationMembership.objects.create(organization=self.team.organization, user=user)
        if scheduled:
            self.task_run.scheduled_at = django_timezone.now() - timedelta(minutes=1)
            self.task_run.save(update_fields=["scheduled_at"])
        get_usage.return_value = CodeUsageStatus(limited, "burst" if limited else None, None, False)
        organization_deactivated.return_value = deactivated
        dispatch = create_dispatch(
            self.task_run,
            TaskWorkflowDispatch.Kind.CREATE,
            build_create_payload(WorkflowDispatchOptions(user_id=user.id)),
            self.task_run.workflow_id,
        )
        claimed = claim_dispatches("dispatcher-1", 1, timedelta(minutes=1))
        self.assertEqual([row.id for row in claimed], [dispatch.id])
        client = Mock(start_workflow=AsyncMock())

        with self.captureOnCommitCallbacks(execute=True):
            async_to_sync(Command()._process)(client, claimed[0], "dispatcher-1", asyncio.Semaphore(1))

        dispatch.refresh_from_db()
        self.task_run.refresh_from_db()
        if scheduled and (limited or deactivated):
            client.start_workflow.assert_not_called()
            self.assertEqual(dispatch.status, TaskWorkflowDispatch.Status.DEAD)
            self.assertEqual(self.task_run.status, TaskRun.Status.FAILED)
            self.assertTrue(self.task_run.error_message)
            self.assertEqual(self.task_run.error_message, dispatch.last_error)
        else:
            client.start_workflow.assert_awaited_once()
            self.assertEqual(dispatch.status, TaskWorkflowDispatch.Status.ACCEPTED)
        if not scheduled:
            get_usage.assert_not_called()

    @parameterized.expand([("member", True), ("removed", False)])
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher._capture_run_feature_flags")
    @patch(
        "products.tasks.backend.management.commands.run_task_workflow_dispatcher._scheduled_run_usage_error",
        return_value=None,
    )
    def test_scheduled_dispatch_requires_private_channel_access(
        self, name: str, member: bool, usage_error: Mock, capture_flags: Mock
    ) -> None:
        user = self.task_run.task.created_by
        assert user is not None
        OrganizationMembership.objects.create(organization=self.team.organization, user=user)
        channel = Channel.objects.for_team(self.team.id).create(
            team=self.team, name="Private", channel_type=Channel.ChannelType.PRIVATE
        )
        membership = ChannelMembership.objects.for_team(self.team.id).create(team=self.team, channel=channel, user=user)
        task = self.task_run.task
        task.channel = channel
        task.save(update_fields=["channel"])
        self.task_run.scheduled_at = django_timezone.now() - timedelta(minutes=1)
        self.task_run.save(update_fields=["scheduled_at"])
        dispatch = create_dispatch(
            self.task_run,
            TaskWorkflowDispatch.Kind.CREATE,
            build_create_payload(WorkflowDispatchOptions(user_id=user.id)),
            self.task_run.workflow_id,
        )
        if not member:
            membership.delete()
        claimed = claim_dispatches("dispatcher-1", 1, timedelta(minutes=1))
        client = Mock(start_workflow=AsyncMock())

        with self.captureOnCommitCallbacks(execute=True):
            async_to_sync(Command()._process)(client, claimed[0], "dispatcher-1", asyncio.Semaphore(1))

        dispatch.refresh_from_db()
        self.task_run.refresh_from_db()
        if member:
            client.start_workflow.assert_awaited_once()
            self.assertEqual(dispatch.status, TaskWorkflowDispatch.Status.ACCEPTED)
        else:
            client.start_workflow.assert_not_called()
            usage_error.assert_not_called()
            self.assertEqual(dispatch.status, TaskWorkflowDispatch.Status.DEAD)
            self.assertEqual(self.task_run.status, TaskRun.Status.FAILED)
            self.assertEqual(self.task_run.error_message, "User no longer has task access")

    @parameterized.expand(
        [
            ("running", WorkflowExecutionStatus.RUNNING, "accepted"),
            ("completed", WorkflowExecutionStatus.COMPLETED, "accepted"),
            ("continued", WorkflowExecutionStatus.CONTINUED_AS_NEW, "accepted"),
            ("failed", WorkflowExecutionStatus.FAILED, "dead"),
            ("canceled", WorkflowExecutionStatus.CANCELED, "dead"),
            ("terminated", WorkflowExecutionStatus.TERMINATED, "dead"),
            ("timed_out", WorkflowExecutionStatus.TIMED_OUT, "dead"),
            ("missing", RPCStatusCode.NOT_FOUND, "dead"),
            ("unavailable", RPCStatusCode.UNAVAILABLE, "pending"),
        ]
    )
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher._capture_run_feature_flags")
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher._scheduled_run_usage_error")
    def test_scheduled_retry_checks_temporal_before_rejecting_usage(
        self,
        name: str,
        workflow_status: WorkflowExecutionStatus | RPCStatusCode,
        expected_status: str,
        usage_error: Mock,
        capture_flags: Mock,
    ) -> None:
        user = self.task_run.task.created_by
        assert user is not None
        OrganizationMembership.objects.create(organization=self.team.organization, user=user)
        self.task_run.scheduled_at = django_timezone.now() - timedelta(minutes=1)
        self.task_run.save(update_fields=["scheduled_at"])
        dispatch = create_dispatch(
            self.task_run,
            TaskWorkflowDispatch.Kind.CREATE,
            build_create_payload(WorkflowDispatchOptions(user_id=user.id)),
            self.task_run.workflow_id,
        )
        client = Mock(start_workflow=AsyncMock(side_effect=TimeoutError("Start response lost")))
        usage_error.return_value = None
        claimed = claim_dispatches("dispatcher-1", 1, timedelta(minutes=1))
        async_to_sync(Command()._process)(client, claimed[0], "dispatcher-1", asyncio.Semaphore(1))

        usage_error.return_value = "Usage limit reached"
        if expected_status == "accepted":
            OrganizationMembership.objects.filter(organization=self.team.organization, user=user).delete()
        describe = AsyncMock(return_value=Mock(status=workflow_status))
        if isinstance(workflow_status, RPCStatusCode):
            describe.side_effect = RPCError("Lookup failed", workflow_status, b"")
        client.get_workflow_handle.return_value.describe = describe
        TaskWorkflowDispatch.objects.for_team(self.team.id).filter(id=dispatch.id).update(
            next_attempt_at=django_timezone.now()
        )
        claimed = claim_dispatches("dispatcher-1", 1, timedelta(minutes=1))

        with self.captureOnCommitCallbacks(execute=True):
            async_to_sync(Command()._process)(client, claimed[0], "dispatcher-1", asyncio.Semaphore(1))

        dispatch.refresh_from_db()
        self.task_run.refresh_from_db()
        self.assertEqual(dispatch.status, expected_status)
        self.assertEqual(
            self.task_run.status, TaskRun.Status.FAILED if expected_status == "dead" else TaskRun.Status.QUEUED
        )
        client.start_workflow.assert_awaited_once()
        self.assertEqual(usage_error.call_count, 2 if expected_status == "dead" else 1)

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

    def test_claims_expired_leases_before_pending_work_and_fills_the_batch(self) -> None:
        now = django_timezone.now()
        pending_runs = [
            TaskRun.objects.create(task=self.task_run.task, team=self.team, status=TaskRun.Status.QUEUED)
            for _ in range(2)
        ]
        pending = [
            TaskWorkflowDispatch.objects.for_team(self.team.id).create(
                team=self.team,
                task_run=run,
                workflow_id=run.workflow_id,
                dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
                payload={"version": 1},
                status=TaskWorkflowDispatch.Status.PENDING,
                next_attempt_at=now - timedelta(minutes=minutes),
            )
            for run, minutes in zip(pending_runs, (2, 1), strict=True)
        ]
        expired = TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=self.task_run,
            workflow_id=self.task_run.workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
            payload={"version": 1},
            status=TaskWorkflowDispatch.Status.CLAIMED,
            claimed_by="dead-dispatcher",
            next_attempt_at=now - timedelta(minutes=1),
            lease_expires_at=now - timedelta(seconds=1),
        )

        with patch("products.tasks.backend.logic.services.workflow_dispatch.django_timezone.now", return_value=now):
            claimed = claim_dispatches("live-dispatcher", 2, timedelta(minutes=1))

        self.assertEqual([row.id for row in claimed], [expired.id, pending[0].id])
        self.assertTrue(all(row.status == TaskWorkflowDispatch.Status.CLAIMED for row in claimed))
        self.assertTrue(all(row.claimed_by == "live-dispatcher" for row in claimed))
        self.assertTrue(all(row.attempt_count == 1 for row in claimed))
        pending[1].refresh_from_db()
        self.assertEqual(pending[1].status, TaskWorkflowDispatch.Status.PENDING)

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

    @patch("products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow")
    def test_scheduled_create_persists_full_run_without_dispatching_early(self, enqueue: Mock) -> None:
        creator_id = self.task_run.task.created_by_id
        assert creator_id is not None
        scheduled_at = django_timezone.now() + timedelta(days=1)

        created = create_and_run_task(
            team=self.team,
            title="Scheduled follow-up",
            description="Review the report after more data arrives",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            user_id=creator_id,
            create_pr=False,
            scheduled_at=scheduled_at,
            runtime_adapter="codex",
            model="gpt-5.6-terra",
            reasoning_effort="high",
            pending_user_message="Revisit the report",
        )

        assert created.latest_run is not None
        run = TaskRun.objects.get(id=created.latest_run.id)
        self.assertEqual(run.status, TaskRun.Status.NOT_STARTED)
        self.assertEqual(run.scheduled_at, scheduled_at)
        self.assertIsNone(run.queued_at)
        self.assertEqual(run.state["runtime_adapter"], "codex")
        self.assertEqual(run.state["model"], "gpt-5.6-terra")
        self.assertEqual(run.state["reasoning_effort"], "high")
        self.assertEqual(run.state["pending_user_message"], "Revisit the report")
        self.assertFalse(TaskWorkflowDispatch.objects.unscoped().filter(task_run=run).exists())
        enqueue.assert_not_called()

    def test_due_materializer_leaves_future_runs_dormant(self) -> None:
        now = django_timezone.now()
        state = {
            "pending_dispatch": {
                "user_id": self.task_run.task.created_by_id,
                "create_pr": False,
                "posthog_mcp_scopes": "full",
                "slack_thread_context": None,
                "workflow_id_prefix": "scheduled",
            }
        }
        due = TaskRun.objects.create(
            task=self.task_run.task,
            team=self.team,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=now - timedelta(minutes=1),
            state=state,
        )
        future = TaskRun.objects.create(
            task=self.task_run.task,
            team=self.team,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=now + timedelta(minutes=1),
            state=state,
        )
        local = TaskRun.objects.create(
            task=self.task_run.task,
            team=self.team,
            environment=TaskRun.Environment.LOCAL,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=now - timedelta(minutes=1),
            state=state,
        )

        self.assertEqual(materialize_due_scheduled_task_runs(100), 1)

        due.refresh_from_db()
        future.refresh_from_db()
        local.refresh_from_db()
        dispatch = TaskWorkflowDispatch.objects.unscoped().get(task_run=due)
        self.assertEqual(due.status, TaskRun.Status.QUEUED)
        self.assertIsNotNone(due.queued_at)
        self.assertEqual(dispatch.payload["create_pr"], False)
        self.assertEqual(dispatch.payload["posthog_mcp_scopes"], "full")
        self.assertEqual(dispatch.workflow_id, f"scheduled-{due.task_id}-{due.id}")
        self.assertEqual(due.workflow_id, dispatch.workflow_id)
        self.assertEqual(future.status, TaskRun.Status.NOT_STARTED)
        self.assertFalse(TaskWorkflowDispatch.objects.unscoped().filter(task_run=future).exists())
        self.assertEqual(local.status, TaskRun.Status.NOT_STARTED)
        self.assertFalse(TaskWorkflowDispatch.objects.unscoped().filter(task_run=local).exists())

    def test_due_materializer_pages_in_schedule_order_without_duplicates(self) -> None:
        now = django_timezone.now()
        state = {
            "pending_dispatch": {
                "user_id": self.task_run.task.created_by_id,
                "create_pr": True,
                "posthog_mcp_scopes": "read_only",
            }
        }
        runs = [
            TaskRun.objects.create(
                task=self.task_run.task,
                team=self.team,
                status=TaskRun.Status.NOT_STARTED,
                scheduled_at=now - timedelta(minutes=minutes),
                state=state,
            )
            for minutes in (3, 2, 1)
        ]

        self.assertEqual(materialize_due_scheduled_task_runs(2), 2)
        self.assertEqual(
            set(TaskRun.objects.filter(status=TaskRun.Status.QUEUED).values_list("id", flat=True)),
            {self.task_run.id, runs[0].id, runs[1].id},
        )
        self.assertEqual(materialize_due_scheduled_task_runs(2), 1)
        self.assertEqual(materialize_due_scheduled_task_runs(2), 0)
        self.assertEqual(
            TaskWorkflowDispatch.objects.unscoped()
            .filter(task_run_id__in=[run.id for run in runs], dispatch_kind=TaskWorkflowDispatch.Kind.CREATE)
            .count(),
            3,
        )

    def test_invalid_due_run_does_not_block_later_scheduled_work(self) -> None:
        now = django_timezone.now()
        invalid_runs = [
            TaskRun.objects.create(
                task=self.task_run.task,
                team=self.team,
                status=TaskRun.Status.NOT_STARTED,
                scheduled_at=now - timedelta(minutes=minutes),
                state=state,
            )
            for minutes, state in [
                (4, {}),
                (3, {"pending_dispatch": {}}),
                (
                    2,
                    {
                        "pending_dispatch": {
                            "user_id": self.task_run.task.created_by_id,
                            "create_pr": False,
                            "posthog_mcp_scopes": "full",
                            "workflow_id_prefix": "x" * 500,
                        }
                    },
                ),
            ]
        ]
        valid = TaskRun.objects.create(
            task=self.task_run.task,
            team=self.team,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=now - timedelta(minutes=1),
            state={
                "pending_dispatch": {
                    "user_id": self.task_run.task.created_by_id,
                    "create_pr": False,
                    "posthog_mcp_scopes": "full",
                }
            },
        )

        self.assertEqual(materialize_due_scheduled_task_runs(4), 1)

        valid.refresh_from_db()
        for invalid in invalid_runs:
            invalid.refresh_from_db()
            self.assertEqual(invalid.status, TaskRun.Status.FAILED)
            self.assertIsNotNone(invalid.completed_at)
            assert invalid.error_message is not None
            self.assertIn("Create a new scheduled task", invalid.error_message)
        self.assertEqual(valid.status, TaskRun.Status.QUEUED)
        self.assertTrue(TaskWorkflowDispatch.objects.unscoped().filter(task_run=valid).exists())

    def test_existing_dispatch_does_not_block_scheduled_batch(self) -> None:
        now = django_timezone.now()
        state = {
            "pending_dispatch": {
                "user_id": self.task_run.task.created_by_id,
                "create_pr": False,
                "posthog_mcp_scopes": "full",
            }
        }
        runs = [
            TaskRun.objects.create(
                task=self.task_run.task,
                team=self.team,
                status=TaskRun.Status.NOT_STARTED,
                scheduled_at=now - timedelta(minutes=minutes),
                state=state,
            )
            for minutes in (2, 1)
        ]
        TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=runs[0],
            workflow_id=runs[0].workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
            payload=build_create_payload(
                WorkflowDispatchOptions(
                    user_id=self.task_run.task.created_by_id,
                    create_pr=False,
                    posthog_mcp_scopes="full",
                )
            ),
        )

        self.assertEqual(materialize_due_scheduled_task_runs(2), 2)

        self.assertEqual(
            set(
                TaskRun.objects.filter(id__in=[run.id for run in runs], status=TaskRun.Status.QUEUED).values_list(
                    "id", flat=True
                )
            ),
            {run.id for run in runs},
        )
        self.assertEqual(
            TaskWorkflowDispatch.objects.unscoped()
            .filter(task_run_id__in=[run.id for run in runs], dispatch_kind=TaskWorkflowDispatch.Kind.CREATE)
            .count(),
            2,
        )

    def test_scheduled_dispatch_uses_canonical_team(self) -> None:
        child_team = Team.objects.create(
            organization=self.team.organization,
            name="Child environment",
            parent_team=self.team,
        )
        task = Task.objects.create(
            team=child_team,
            created_by=self.task_run.task.created_by,
            title="Child task",
            description="Child task",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        run = TaskRun.objects.create(
            task=task,
            team=child_team,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=django_timezone.now() - timedelta(minutes=1),
            state={
                "pending_dispatch": {
                    "user_id": self.task_run.task.created_by_id,
                    "create_pr": False,
                    "posthog_mcp_scopes": "full",
                }
            },
        )

        self.assertEqual(materialize_due_scheduled_task_runs(1), 1)

        dispatch = TaskWorkflowDispatch.objects.unscoped().get(task_run=run)
        self.assertEqual(dispatch.team_id, self.team.id)
        self.assertEqual(TaskWorkflowDispatch.objects.for_team(child_team.id).get(task_run=run), dispatch)

    def test_deleting_task_cancels_scheduled_runs(self) -> None:
        now = django_timezone.now()
        state = {
            "pending_dispatch": {
                "user_id": self.task_run.task.created_by_id,
                "create_pr": False,
                "posthog_mcp_scopes": "full",
            }
        }
        due = TaskRun.objects.create(
            task=self.task_run.task,
            team=self.team,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=now - timedelta(minutes=1),
            state=state,
        )
        future = TaskRun.objects.create(
            task=self.task_run.task,
            team=self.team,
            status=TaskRun.Status.NOT_STARTED,
            scheduled_at=now + timedelta(days=1),
            state=state,
        )
        self.assertEqual(materialize_due_scheduled_task_runs(1), 1)

        due.task.soft_delete()

        due.refresh_from_db()
        future.refresh_from_db()
        dispatch = TaskWorkflowDispatch.objects.unscoped().get(task_run=due)
        self.assertEqual(due.status, TaskRun.Status.CANCELLED)
        self.assertEqual(future.status, TaskRun.Status.CANCELLED)
        self.assertEqual(dispatch.status, TaskWorkflowDispatch.Status.DEAD)
        self.assertEqual(materialize_due_scheduled_task_runs(10), 0)

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
    @parameterized.expand([("allowed", None), ("blocked", "Usage limit reached"), ("error", "error")])
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.close_old_connections")
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.usage_limit_response")
    def test_usage_worker_releases_connections(
        self, name: str, error: str | None, usage_response: Mock, close_connections: Mock
    ) -> None:
        user = Mock()
        if name == "error":
            usage_response.side_effect = RuntimeError(error)
            with self.assertRaises(RuntimeError):
                _scheduled_run_usage_error(user, 1)
        else:
            usage_response.return_value = Mock(data={"error": error}) if error is not None else None
            self.assertEqual(_scheduled_run_usage_error(user, 1), error)
        self.assertEqual(close_connections.call_count, 2)

    def test_scheduled_usage_checks_do_not_block_each_other(self) -> None:
        barrier = threading.Barrier(2, timeout=5)
        run = Mock(status=TaskRun.Status.QUEUED, scheduled_at=django_timezone.now())
        dispatches = [
            Mock(
                id=dispatch_id,
                dispatch_kind=TaskWorkflowDispatch.Kind.CREATE,
                attempt_count=1,
                payload=build_create_payload(WorkflowDispatchOptions(user_id=1)),
            )
            for dispatch_id in ("first", "second")
        ]
        client = Mock(start_workflow=AsyncMock())

        def usage_error(user: User, team_id: int) -> None:
            barrier.wait()

        async def process() -> None:
            semaphore = asyncio.Semaphore(2)
            await asyncio.gather(
                *(Command()._process(client, dispatch, "worker", semaphore) for dispatch in dispatches)
            )

        module = "products.tasks.backend.management.commands.run_task_workflow_dispatcher"
        with (
            patch(f"{module}.TaskRun.objects") as runs,
            patch(f"{module}.Team.objects.aget", new_callable=AsyncMock),
            patch(f"{module}.User.objects.aget", new_callable=AsyncMock),
            patch(f"{module}.dispatch_exceeded_max_age", return_value=False),
            patch(f"{module}._user_can_dispatch", return_value=True),
            patch(f"{module}._scheduled_run_usage_error", side_effect=usage_error),
            patch(f"{module}._capture_run_feature_flags"),
            patch(f"{module}.mark_accepted"),
            patch(f"{module}.observe_task_run_workflow_start"),
            patch(f"{module}.reschedule") as reschedule_dispatch,
        ):
            runs.select_related.return_value.aget = AsyncMock(return_value=run)
            asyncio.run(process())

        self.assertEqual(client.start_workflow.await_count, 2)
        reschedule_dispatch.assert_not_called()

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
