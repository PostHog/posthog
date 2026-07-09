from unittest.mock import patch

from django.core.cache import cache
from django.db import InterfaceError, OperationalError
from django.test import TestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.push_dispatcher import (
    notify_task_run_awaiting_input,
    notify_task_run_cancelled,
    notify_task_run_completed,
    notify_task_run_failed,
)


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
            ("completed", notify_task_run_completed, "finished"),
            ("failed", notify_task_run_failed, "failed"),
            ("cancelled", notify_task_run_cancelled, "cancelled"),
            ("awaiting", notify_task_run_awaiting_input, "needs your input"),
        ]
    )
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_notify_enqueues_push(self, _name, notify_fn, expected_body_fragment, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            notify_fn(self.task_run)
        mock_delay.assert_called_once()
        user_id, title, body, data, suppressed = mock_delay.call_args.args
        self.assertEqual(user_id, self.user.id)
        self.assertEqual(title, "PostHog Code")
        self.assertIn(expected_body_fragment, body)
        self.assertEqual(data["taskId"], str(self.task.id))
        self.assertEqual(data["taskRunId"], str(self.task_run.id))
        # No presence rows in this test's setUp, so nothing to suppress.
        self.assertEqual(suppressed, [])

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_cooldown_collapses_duplicates(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
            notify_task_run_completed(self.task_run)
        self.assertEqual(mock_delay.call_count, 1)

    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_cooldown_is_per_kind(self, mock_delay):
        # Different push kinds on the same run shouldn't share a cooldown key.
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(self.task_run)
            notify_task_run_awaiting_input(self.task_run)
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
        """The dispatcher MUST NOT raise. Any DB / Redis hiccup must be
        swallowed so it can't fail the task lifecycle activity that
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
