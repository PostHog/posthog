from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.models import Task
from products.tasks.backend.turn_completed import dispatch_turn_completed


class TestDispatchTurnCompleted(BaseTest):
    @parameterized.expand(
        [
            ("interactive_turn", "interactive", True, True),
            ("idle_resume", "interactive", False, False),
            ("background_run", "background", True, False),
        ]
    )
    def test_fans_out_only_for_a_completed_interactive_turn(
        self, _name: str, mode: str, turn_completed: bool, expected: bool
    ) -> None:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        task_run = task.create_run(mode=mode)

        with (
            patch("products.tasks.backend.push_dispatcher.notify_task_run_turn_completed") as notify,
            patch("products.tasks.backend.turn_completed.enqueue_turn_suggestion") as enqueue,
        ):
            assert dispatch_turn_completed(task_run, turn_completed=turn_completed) is expected

        assert notify.called is expected
        assert enqueue.called is expected
