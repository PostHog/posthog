from collections.abc import Callable
from contextlib import nullcontext
from uuid import uuid4

import time_machine
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import InterfaceError, OperationalError, transaction
from django.test import TestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.tasks.push_notifications import send_user_push

from products.tasks.backend.awaiting_input import dispatch_awaiting_input
from products.tasks.backend.logic.stream.push_message import PushMessage
from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
from products.tasks.backend.models import Channel, ChannelMembership, Task, TaskRun
from products.tasks.backend.push_dispatcher import (
    notify_task_handoff,
    notify_task_run_awaiting_input,
    notify_task_run_cancelled,
    notify_task_run_completed,
    notify_task_run_failed,
    notify_task_run_turn_completed,
)
from products.tasks.backend.redis import get_tasks_stream_redis_sync


# The Celery dispatch is deferred via transaction.on_commit, which never fires
# inside TestCase's rolled-back transaction — tests wrap notify calls in
# captureOnCommitCallbacks(execute=True) to run the deferred callback (or assert
# none was registered) without TransactionTestCase's per-test full-DB flush.
class TestPushDispatcher(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="push@example.com", first_name="Push", password="password")
        # Push dispatch requires the recipient to still be a member of the team's org —
        # see the access check in push_dispatcher._enqueue.
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.task = Task.objects.create(
            team=self.team,
            title="My Task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)

    @parameterized.expand(
        [
            ("completed", notify_task_run_completed, "finished", None, "  Updated chat  "),
            ("completed", notify_task_run_completed, "Fixed the chart.", "Fixed the chart.", "  Updated chat  "),
            ("failed", notify_task_run_failed, "failed", None, "  Updated chat  "),
            ("cancelled", notify_task_run_cancelled, "cancelled", None, "  Updated chat  "),
            ("awaiting", notify_task_run_awaiting_input, "needs your input", None, "  Updated chat  "),
            ("turn_completed", notify_task_run_turn_completed, "finished", None, "  Updated chat  "),
            ("turn_completed", notify_task_run_turn_completed, "Current reply.", "Current reply.", "  Updated chat  "),
            ("turn_completed", notify_task_run_turn_completed, "finished", None, ""),
        ]
    )
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_notify_enqueues_push(
        self,
        _name: str,
        notify_fn: Callable[[TaskRun], object],
        expected_body_fragment: str,
        preview: str | None,
        chat_title: str,
        mock_delay: Mock,
    ) -> None:
        Task.objects.filter(id=self.task.id, team_id=self.team.id).update(title=chat_title)
        key = f"{get_task_run_stream_key(str(self.task_run.id))}:push-message"
        client = get_tasks_stream_redis_sync()
        if preview is not None:
            self.task_run.output = {"final_message": "Previous reply."}
            client.set(key, PushMessage(text=preview).to_json(), ex=60)
        self.addCleanup(client.delete, key)
        with self.captureOnCommitCallbacks(execute=True):
            notify_fn(self.task_run)
        mock_delay.assert_called_once()
        user_id, title, body, data, suppressed = mock_delay.call_args.args
        self.assertEqual(user_id, self.user.id)
        self.assertEqual(title, chat_title.strip() or "Untitled task")
        self.assertIn(expected_body_fragment, body)
        self.assertEqual(data["taskId"], str(self.task.id))
        self.assertEqual(data["projectId"], str(self.task.team_id))
        self.assertEqual(data["taskRunId"], str(self.task_run.id))
        self.assertEqual(data["notificationKind"], _name)
        # No presence rows in this test's setUp, so nothing to suppress.
        self.assertEqual(suppressed, [])

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_trial_completion_does_not_notify_the_operator(self, mock_delay) -> None:
        self.task.origin_product = Task.OriginProduct.SIGNALS_SCOUT
        self.task.origin_key = f"scout-trial:{uuid4()}"
        self.task.save(update_fields=["origin_product", "origin_key"])

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)

        mock_delay.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_cooldown_collapses_duplicates(self, mock_delay):
        labels = {"kind": "completed", "outcome": "cooldown_deduped"}
        before = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_outcomes_total", labels) or 0.0
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
        self.assertEqual(mock_delay.call_count, 1)
        after = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_outcomes_total", labels) or 0.0
        self.assertEqual(after, before + 2)

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_cooldown_is_per_kind(self, mock_delay):
        # Different push kinds on the same run shouldn't share a cooldown key.
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_awaiting_input(self.task_run)
            notify_task_run_turn_completed(self.task_run)
        self.assertEqual(mock_delay.call_count, 3)

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_awaiting_cooldown_is_shared_by_permission_requests_and_turn_end(self, mock_delay) -> None:
        self.task_run.state = {"mode": "interactive"}
        with time_machine.travel("2026-10-20T12:00:00Z", tick=False) as clock:
            with self.captureOnCommitCallbacks(execute=True):
                dispatch_awaiting_input(self.task_run, request_id="request-1")
                dispatch_awaiting_input(self.task_run, request_id="request-2")
                notify_task_run_awaiting_input(self.task_run)
            self.assertEqual(mock_delay.call_count, 1)

            clock.shift(31)
            with self.captureOnCommitCallbacks(execute=True):
                dispatch_awaiting_input(self.task_run, request_id="request-1")
                dispatch_awaiting_input(self.task_run, request_id="request-3")
            self.assertEqual(mock_delay.call_count, 2)

    @parameterized.expand(["prepare", "immediate", "deferred", "rollback"])
    def test_awaiting_request_can_retry_after_failed_enqueue(self, failure: str) -> None:
        self.task_run.state = {"mode": "interactive"}
        with (
            time_machine.travel("2026-10-20T12:00:00Z", tick=False) as clock,
            patch("products.tasks.backend.push_dispatcher._project_awaiting_input_activity"),
            patch("products.tasks.backend.push_dispatcher.send_user_push.delay") as send_push,
        ):
            send_push.side_effect = RuntimeError("broker unavailable")
            with (
                patch(
                    "products.tasks.backend.push_dispatcher._suppressed_push_token_ids_for_task",
                    side_effect=OperationalError("connection unavailable"),
                )
                if failure == "prepare"
                else nullcontext(),
                patch("products.tasks.backend.push_dispatcher.transaction.on_commit", side_effect=lambda fn: fn())
                if failure == "immediate"
                else nullcontext(),
                self.captureOnCommitCallbacks(execute=True),
                transaction.atomic(),
            ):
                scheduled = dispatch_awaiting_input(self.task_run, request_id="retry-request")
                self.assertEqual(scheduled, failure in ("deferred", "rollback"))
                if failure == "rollback":
                    transaction.set_rollback(True)
            self.assertEqual(send_push.call_count, int(failure in ("immediate", "deferred")))

            clock.shift(31)
            send_push.reset_mock()
            send_push.side_effect = None
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(dispatch_awaiting_input(self.task_run, request_id="retry-request"))
                send_push.assert_not_called()
            send_push.assert_called_once()

            clock.shift(31)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertFalse(dispatch_awaiting_input(self.task_run, request_id="retry-request"))
            send_push.assert_called_once()

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_handoff_cooldown_distinguishes_announcements(self, mock_delay):
        announcement_id = uuid4()
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=announcement_id)
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=announcement_id)
            notify_task_handoff(self.task, recipient=self.user, actor=self.user, message_id=uuid4())
        self.assertEqual(mock_delay.call_count, 2)

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_recipient_without_team_access_is_skipped(self, mock_delay):
        """A user who has been removed from the task's organization must not receive
        pushes carrying that task's title — losing access should mean losing notifications."""
        outsider = User.objects.create_user(email="outsider@example.com", first_name="Out", password="x")
        outsider_task = Task.objects.create(
            team=self.team,
            title="Sensitive Task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=outsider,
        )
        outsider_run = TaskRun.objects.create(task=outsider_task, team=self.team)

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(outsider_run)
        mock_delay.assert_not_called()

    @parameterized.expand(
        [
            ("removed_cached_reply", Channel.ChannelType.PRIVATE, True, "cached", False),
            ("removed_final_reply", Channel.ChannelType.PRIVATE, True, "final", False),
            ("removed_status", Channel.ChannelType.PRIVATE, True, "status", False),
            ("private_member", Channel.ChannelType.PRIVATE, False, "cached", True),
            ("personal_owner", Channel.ChannelType.PERSONAL, False, "cached", True),
            ("public_channel", Channel.ChannelType.PUBLIC, False, "cached", True),
        ]
    )
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_notification_requires_channel_access(
        self,
        _name: str,
        channel_type: str,
        remove_membership: bool,
        preview_source: str,
        expected_push: bool,
        mock_delay: Mock,
    ) -> None:
        channel = Channel.objects.for_team(self.team.id).create(
            team=self.team, name="Test channel", channel_type=channel_type, created_by=self.user
        )
        self.task.channel = channel
        self.task.save(update_fields=["channel"])
        if channel_type == Channel.ChannelType.PRIVATE:
            membership = ChannelMembership.objects.for_team(self.team.id).create(
                team=self.team, channel=channel, user=self.user
            )
            if remove_membership:
                membership.delete()

        key = f"{get_task_run_stream_key(str(self.task_run.id))}:push-message"
        client = get_tasks_stream_redis_sync()
        self.addCleanup(client.delete, key)
        if preview_source == "cached":
            client.set(key, PushMessage(text="Reply content.").to_json(), ex=60)
        elif preview_source == "final":
            self.task_run.output = {"final_message": "Reply content."}

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
        if expected_push:
            mock_delay.assert_called_once()
            self.assertEqual(mock_delay.call_args.args[2], "Reply content.")
        else:
            mock_delay.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_anonymous_task_is_noop(self, mock_delay):
        anonymous_task = Task.objects.create(
            team=self.team,
            title="Anon",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=None,
        )
        anonymous_run = TaskRun.objects.create(task=anonymous_task, team=self.team)
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(anonymous_run)
        mock_delay.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher._enqueue_inner", side_effect=RuntimeError("redis is down"))
    def test_enqueue_swallows_unexpected_errors(self, _mock_inner):
        """The dispatcher MUST NOT raise. Any DB / Redis hiccup
        must be swallowed so it can't fail the task lifecycle activity that
        triggered the push."""
        # The bare except in _enqueue should catch the RuntimeError. If it
        # doesn't, this test raises and fails — which is the regression signal.
        notify_task_run_completed(self.task_run)

    @parameterized.expand(
        [
            (
                "db_connection_operational",
                "db_connection",
                OperationalError("server closed the connection unexpectedly"),
            ),
            ("db_connection_interface", "db_connection", InterfaceError("connection already closed")),
            ("other", "other", RuntimeError("redis is down")),
        ]
    )
    def test_swallowed_failure_increments_metric(self, _name, expected_reason, exc):
        labels = {"kind": "completed", "reason": expected_reason}
        before = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_failures_total", labels) or 0.0
        with patch("products.tasks.backend.push_dispatcher._enqueue_inner", side_effect=exc):
            notify_task_run_completed(self.task_run)
        after = REGISTRY.get_sample_value("posthog_tasks_push_dispatcher_failures_total", labels) or 0.0
        self.assertEqual(after, before + 1)

    @patch("products.tasks.backend.push_dispatcher.notify_task_run_completed")
    def test_mark_completed_triggers_push(self, mock_notify):
        self.task_run.mark_completed()
        mock_notify.assert_called_once_with(self.task_run)

    @patch("products.tasks.backend.push_dispatcher.notify_task_run_failed")
    def test_mark_failed_triggers_push(self, mock_notify):
        self.task_run.mark_failed("nope")
        mock_notify.assert_called_once_with(self.task_run)

    @patch("posthog.tasks.push_notifications.send_push_to_user", return_value=2)
    def test_delivery_task_records_expo_acceptance(self, mock_send):
        labels = {"kind": "completed", "outcome": "accepted"}
        before = REGISTRY.get_sample_value("posthog_push_delivery_outcomes_total", labels) or 0.0

        send_user_push(
            self.user.id,
            "posthog",
            "Finished",
            {"notificationKind": "completed"},
        )

        mock_send.assert_called_once()
        after = REGISTRY.get_sample_value("posthog_push_delivery_outcomes_total", labels) or 0.0
        self.assertEqual(after, before + 1)
