from posthog.test.base import BaseTest
from unittest.mock import patch

from products.tasks.backend.models import Task
from products.tasks.backend.turn_completed import on_interactive_turn_completed

MODULE = "products.tasks.backend.turn_completed"


class TestOnInteractiveTurnCompleted(BaseTest):
    def test_fans_out_to_the_push_notification_and_the_suggestion(self):
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        task_run = task.create_run(mode="interactive")

        with (
            patch(f"{MODULE}.notify_task_run_turn_completed") as notify,
            patch(f"{MODULE}.enqueue_turn_suggestion") as enqueue,
        ):
            on_interactive_turn_completed(task_run)

        notify.assert_called_once_with(task_run)
        enqueue.assert_called_once_with(task_run)
