from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.tasks.backend.facade.task_run_signals import task_run_turn_completed
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.turn_completed import dispatch_turn_completed


class TestDispatchTurnCompleted(BaseTest):
    def _run(self, mode: str) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        return task.create_run(mode=mode)

    def _connect(self, receiver: Callable[..., None]) -> None:
        task_run_turn_completed.connect(receiver, sender=TaskRun, dispatch_uid="test_turn_completed")
        self.addCleanup(task_run_turn_completed.disconnect, sender=TaskRun, dispatch_uid="test_turn_completed")

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
        task_run = self._run(mode)
        receiver = MagicMock()
        self._connect(receiver)

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_turn_completed") as notify:
            assert dispatch_turn_completed(task_run, turn_completed=turn_completed) is expected

        assert notify.called is expected
        assert receiver.called is expected
        if expected:
            assert receiver.call_args.kwargs["task_run"] == task_run

    def test_a_failing_push_does_not_suppress_the_signal(self) -> None:
        receiver = MagicMock()
        self._connect(receiver)

        with (
            patch(
                "products.tasks.backend.push_dispatcher.notify_task_run_turn_completed",
                side_effect=RuntimeError("push down"),
            ),
            self.assertRaises(RuntimeError),
        ):
            dispatch_turn_completed(self._run("interactive"))

        assert receiver.called

    def test_a_failing_receiver_does_not_fail_the_report(self) -> None:
        def failing_receiver(**kwargs: object) -> None:
            raise RuntimeError("boom")

        self._connect(failing_receiver)

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_turn_completed"):
            assert dispatch_turn_completed(self._run("interactive")) is True
