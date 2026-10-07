from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.delegate_task import DelegateTaskInput, brief_task_run
from products.tasks.backend.temporal.delegate_task.activities import queue_briefed_run


class TestDelegateTaskActivities(BaseTest):
    def _deferred_run(self) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="placeholder",
            description="Find out why signups dropped.",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        return task.create_run(
            extra_state={"pending_dispatch": {"posthog_mcp_scopes": ["insight:read"], "user_id": self.user.id}},
            acting_user_id=self.user.id,
            defer_dispatch=True,
            stage="briefing",
        )

    @patch("products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow")
    def test_dispatch_queues_the_run_with_the_briefed_scopes(self, mock_enqueue) -> None:
        run = self._deferred_run()

        queue_briefed_run(str(run.id))

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.stage)
        self.assertIsNotNone(run.queued_at)
        self.assertNotIn("dispatch_deferred", run.state)
        options = mock_enqueue.call_args.kwargs["options"]
        self.assertEqual(options.user_id, self.user.id)
        self.assertEqual(options.posthog_mcp_scopes, ["insight:read"])

    @patch("products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow")
    def test_dispatch_leaves_a_run_whose_task_was_deleted(self, mock_enqueue) -> None:
        run = self._deferred_run()
        run.task.soft_delete()

        queue_briefed_run(str(run.id))

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_enqueue.assert_not_called()

    def test_brief_refuses_a_run_that_is_no_longer_waiting(self) -> None:
        run = self._deferred_run()
        TaskRun.objects.filter(pk=run.pk).update(status=TaskRun.Status.CANCELLED)

        with self.assertRaises(ApplicationError) as raised:
            async_to_sync(brief_task_run)(DelegateTaskInput(run_id=str(run.id)))

        self.assertTrue(raised.exception.non_retryable)
