from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team, User
from posthog.models.user_push_token import UserPushToken

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.push_dispatcher import (
    notify_task_run_awaiting_input,
    notify_task_run_cancelled,
    notify_task_run_completed,
    notify_task_run_failed,
)


class TestPushDispatcher(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="push@example.com", first_name="Push", password="password")
        self.task = Task.objects.create(
            team=self.team,
            title="My Task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[abc]", platform="ios")

    @patch("products.tasks.backend.push_dispatcher.send_push_to_user")
    def test_notify_completed_sends_push(self, mock_send):
        notify_task_run_completed(self.task_run)
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["title"], "PostHog Code")
        self.assertIn("finished", kwargs["body"])
        self.assertEqual(kwargs["data"]["taskRunId"], str(self.task_run.id))
        self.assertEqual(kwargs["data"]["taskId"], str(self.task.id))

    @patch("products.tasks.backend.push_dispatcher.send_push_to_user")
    def test_notify_failed_sends_push(self, mock_send):
        notify_task_run_failed(self.task_run)
        mock_send.assert_called_once()
        self.assertIn("failed", mock_send.call_args.kwargs["body"])

    @patch("products.tasks.backend.push_dispatcher.send_push_to_user")
    def test_notify_cancelled_sends_push(self, mock_send):
        notify_task_run_cancelled(self.task_run)
        mock_send.assert_called_once()
        self.assertIn("cancelled", mock_send.call_args.kwargs["body"])

    @patch("products.tasks.backend.push_dispatcher.send_push_to_user")
    def test_notify_awaiting_input_sends_push(self, mock_send):
        notify_task_run_awaiting_input(self.task_run)
        mock_send.assert_called_once()
        self.assertIn("needs your input", mock_send.call_args.kwargs["body"])

    @patch("products.tasks.backend.push_dispatcher.send_push_to_user")
    def test_notify_no_creator_is_noop(self, mock_send):
        anonymous_task = Task.objects.create(
            team=self.team,
            title="Anon",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=None,
        )
        anonymous_run = TaskRun.objects.create(task=anonymous_task, team=self.team)
        notify_task_run_completed(anonymous_run)
        mock_send.assert_not_called()

    @patch("products.tasks.backend.push_dispatcher.send_push_to_user", side_effect=RuntimeError("boom"))
    def test_notify_swallows_dispatcher_errors(self, _mock_send):
        # Push failures must not bubble up — the task lifecycle keeps going.
        notify_task_run_completed(self.task_run)

    @patch("products.tasks.backend.push_dispatcher.notify_task_run_completed")
    def test_mark_completed_triggers_push(self, mock_notify):
        self.task_run.mark_completed()
        mock_notify.assert_called_once_with(self.task_run)

    @patch("products.tasks.backend.push_dispatcher.notify_task_run_failed")
    def test_mark_failed_triggers_push(self, mock_notify):
        self.task_run.mark_failed("nope")
        mock_notify.assert_called_once_with(self.task_run)
