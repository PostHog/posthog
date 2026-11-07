from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from products.tasks.backend.exceptions import ActiveSessionCapError
from products.tasks.backend.logic.services.sandbox_usage import SandboxCpuAttribution
from products.tasks.backend.logic.services.warm import SandboxWarmer
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_WATCHED_TIMEOUT,
    get_task_run_stream_key,
    get_task_run_stream_watched_key,
)
from products.tasks.backend.models import SandboxSession, Task, TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    STEER_DECLINE_REASON_UNREPORTED,
    SendFollowupToSandboxInput,
    _get_stop_reason,
    _steer_decline_reason,
    _write_turn_complete,
    send_followup_to_sandbox,
)

_ACTIVITY = "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox"


class TestGetStopReason(SimpleTestCase):
    def test_returns_result_stop_reason_when_present(self):
        self.assertEqual(_get_stop_reason({"result": {"stopReason": "max_tokens"}}), "max_tokens")

    def test_defaults_to_end_turn_when_missing(self):
        self.assertEqual(_get_stop_reason({"result": {}}), "end_turn")
        self.assertEqual(_get_stop_reason({}), "end_turn")
        self.assertEqual(_get_stop_reason(None), "end_turn")

    def test_defaults_to_end_turn_when_result_is_not_a_dict(self):
        self.assertEqual(_get_stop_reason({"result": "ok"}), "end_turn")


class TestSteerDeclineReason(SimpleTestCase):
    @parameterized.expand(
        [
            ("startup_turn", {"result": {"steered": False, "reason": "startup_turn"}}, "startup_turn"),
            ("no_active_turn", {"result": {"steered": False, "reason": "no_active_turn"}}, "no_active_turn"),
            ("adapter_rejected", {"result": {"steered": False, "reason": "adapter_rejected"}}, "adapter_rejected"),
            ("older_sandbox_omits_reason", {"result": {"steered": False}}, STEER_DECLINE_REASON_UNREPORTED),
            ("reason_outside_result", {"reason": "startup_turn"}, STEER_DECLINE_REASON_UNREPORTED),
            ("result_is_not_a_dict", {"result": "steer_declined"}, STEER_DECLINE_REASON_UNREPORTED),
            ("empty_reason", {"result": {"reason": ""}}, STEER_DECLINE_REASON_UNREPORTED),
            ("no_data", None, STEER_DECLINE_REASON_UNREPORTED),
        ]
    )
    def test_reads_reason_from_command_result(self, _name, data, expected):
        self.assertEqual(_steer_decline_reason(data), expected)


class TestWriteTurnComplete(BaseTest):
    @patch(
        "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.publish_task_run_stream_event"
    )
    def test_writes_stop_reason_to_synthetic_event(self, mock_publish):
        _write_turn_complete("run-123", "max_tokens")

        event = mock_publish.call_args.args[1]
        self.assertEqual(event["notification"]["method"], "_posthog/turn_complete")
        self.assertEqual(event["notification"]["params"]["stopReason"], "max_tokens")

    def test_presence_gated_write_skips_unwatched_stream_and_sets_ttl_when_watched(self):
        run_id = f"test:{uuid4()}"
        stream_key = get_task_run_stream_key(run_id)
        watched_key = get_task_run_stream_watched_key(stream_key)
        client = get_tasks_stream_redis_sync()
        try:
            _write_turn_complete(run_id, presence_gated=True)
            self.assertFalse(client.exists(stream_key))

            client.set(watched_key, "1", ex=TASK_RUN_STREAM_WATCHED_TIMEOUT)
            _write_turn_complete(run_id, presence_gated=True)
            self.assertEqual(client.xlen(stream_key), 1)
            self.assertGreater(client.ttl(stream_key), 0)
        finally:
            client.delete(stream_key, watched_key)


@patch("products.tasks.backend.logic.services.sandbox_usage.record_task_run_user_activity", new=MagicMock())
@patch("products.tasks.backend.logic.services.sandbox_usage.claim_task_run_sandbox_sessions", new=MagicMock())
class TestSendFollowupToSandbox(BaseTest):
    @patch(
        "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.publish_task_run_stream_event"
    )
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message")
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun.objects")
    def test_propagates_stop_reason_from_command_result(
        self, mock_task_run_objects, mock_send_user_message, mock_publish
    ):
        task_run = MagicMock()
        task_run.id = uuid4()
        task_run.team_id = self.team.id
        task_run.state = {}
        task_run.task.created_by = None
        mock_task_run_objects.select_related.return_value.get.return_value = task_run
        mock_send_user_message.return_value = MagicMock(
            success=True,
            data={"result": {"stopReason": "max_tokens"}},
        )

        ActivityEnvironment().run(
            send_followup_to_sandbox, SendFollowupToSandboxInput(run_id="run-123", message="hello")
        )

        event = mock_publish.call_args.args[1]
        self.assertEqual(event["notification"]["params"]["stopReason"], "max_tokens")

    # A bare mock would return a truthy value, which now reads as a rebind failure.
    @patch(
        "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._refresh_sandbox_mcp",
        return_value=None,
    )
    @patch(
        "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.publish_task_run_stream_event"
    )
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message")
    @patch("products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun.objects")
    def test_steer_skips_refresh_and_synthetic_turn_complete(
        self,
        mock_task_run_objects,
        mock_send_user_message,
        mock_publish,
        mock_refresh_sandbox_mcp,
    ):
        task_run = MagicMock()
        task_run.id = uuid4()
        task_run.team_id = self.team.id
        task_run.state = {"sandbox_id": "sandbox-123"}
        task_run.task.created_by_id = 42
        task_run.task.created_by = MagicMock(id=42)
        task_run.task.stored_profile = None
        mock_task_run_objects.select_related.return_value.get.return_value = task_run
        mock_send_user_message.return_value = MagicMock(
            success=True,
            data={"result": {"stopReason": "steered", "steered": True}},
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.get_sandbox_mcp_session_user",
                return_value=42,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_sandbox_connection_token",
                return_value=None,
            ),
        ):
            ActivityEnvironment().run(
                send_followup_to_sandbox,
                SendFollowupToSandboxInput(
                    run_id="run-123",
                    message="change direction",
                    actor_user_id=42,
                    steer=True,
                ),
            )

        mock_refresh_sandbox_mcp.assert_not_called()
        mock_send_user_message.assert_called_once_with(
            task_run,
            "change direction",
            artifacts=None,
            auth_token=None,
            timeout=1800,
            message_id=None,
            steer=True,
        )
        mock_publish.assert_not_called()


@patch(f"{_ACTIVITY}._refresh_sandbox_github", return_value=None)
@patch(f"{_ACTIVITY}._refresh_sandbox_mcp", return_value=None)
@patch(f"{_ACTIVITY}.create_sandbox_connection_token", return_value=None)
@patch(f"{_ACTIVITY}.publish_task_run_stream_event")
@patch("products.tasks.backend.logic.services.sandbox_usage.measure_task_run_cpu_attribution", return_value={})
@patch(f"{_ACTIVITY}.send_user_message")
class TestSendFollowupSandboxAttribution(BaseTest):
    def _run_with_session(self, *, attributed: bool) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Warm",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, state={})
        now = timezone.now()
        SandboxSession.objects.unscoped().create(
            team=self.team,
            task_run=run,
            sandbox_id=f"sb-{run.id}",
            cpu_cores=4.0,
            memory_gb=16.0,
            ttl_seconds=3600,
            ttl_expires_at=now + timedelta(hours=1),
            prewarmed=True,
            user_attributed_at=now if attributed else None,
            origin_product=task.origin_product,
        )
        return run

    @parameterized.expand([("warm_claim", False), ("already_attributed", True)])
    def test_delivery_stamps_user_activity(
        self, _name, attributed, mock_send, mock_measure, _publish, _token, _mcp, _github
    ) -> None:
        run = self._run_with_session(attributed=attributed)
        session = SandboxSession.objects.unscoped().get(task_run=run)
        measured_at = timezone.now() - timedelta(seconds=5)
        mock_measure.return_value = {
            session.sandbox_id: SandboxCpuAttribution(
                cpu_usage_usec=1_000, billed_cpu_usage_usec=None, measured_at=measured_at
            )
        }
        attributed_at_send = []

        def send(*args, **kwargs):
            attributed_at_send.append(SandboxSession.objects.unscoped().get(id=session.id).user_attributed_at)
            return MagicMock(success=True, turn_in_flight=False, data={"result": {}})

        mock_send.side_effect = send

        ActivityEnvironment().run(
            send_followup_to_sandbox, SendFollowupToSandboxInput(run_id=str(run.id), message="hi")
        )

        session.refresh_from_db()
        assert attributed_at_send == [session.user_attributed_at]
        assert (session.user_attributed_at == measured_at) is not attributed
        assert session.last_user_activity_at is not None
        assert mock_measure.called is not attributed

    def test_warm_claim_at_the_active_session_cap_is_refused(
        self, mock_send, _measure, _publish, _token, _mcp, _github
    ) -> None:
        busy_run = self._run_with_session(attributed=True)
        now = timezone.now()
        for i in range(SandboxWarmer.ORIGIN_ACTIVE_SESSION_CAPS[Task.OriginProduct.USER_CREATED].per_user - 1):
            SandboxSession.objects.unscoped().create(
                team=self.team,
                task_run=busy_run,
                sandbox_id=f"sb-busy-{i}",
                cpu_cores=4.0,
                memory_gb=16.0,
                ttl_seconds=3600,
                ttl_expires_at=now + timedelta(hours=1),
                user_attributed_at=now,
                origin_product=Task.OriginProduct.USER_CREATED,
            )
        run = self._run_with_session(attributed=False)

        with self.assertRaises(ActiveSessionCapError) as error_context:
            ActivityEnvironment().run(
                send_followup_to_sandbox, SendFollowupToSandboxInput(run_id=str(run.id), message="hi")
            )

        assert error_context.exception.non_retryable is True
        assert error_context.exception.context["scope"] == "user"
        mock_send.assert_not_called()
        assert SandboxSession.objects.unscoped().get(task_run=run).user_attributed_at is None
