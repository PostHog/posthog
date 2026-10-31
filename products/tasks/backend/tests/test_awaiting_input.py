from collections.abc import Callable
from uuid import uuid4

import time_machine
from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.awaiting_input import dispatch_awaiting_input
from products.tasks.backend.models import TaskRun


class TestAwaitingInput(SimpleTestCase):
    @staticmethod
    def _enqueue_successfully(task_run: TaskRun, *, on_enqueued: Callable[[], None]) -> bool:
        on_enqueued()
        return True

    @parameterized.expand(
        [
            ("replayed_request", "request-1", False, 31, 1),
            ("new_request", "request-2", False, 31, 2),
            ("rapid_new_request", "request-2", False, 0, 1),
            ("another_run", "request-1", True, 0, 2),
            ("maximum_length", "r" * 200, False, 31, 2),
        ]
    )
    def test_deduplicates_by_run_and_request_across_replays(
        self, _name: str, request_id: str, another_run: bool, elapsed: int, expected_pushes: int
    ) -> None:
        task_run = TaskRun(id=uuid4(), state={"mode": "interactive"})
        replay_run = TaskRun(id=task_run.id, state=task_run.state)
        if another_run:
            replay_run.id = uuid4()
        cache = LocMemCache(str(uuid4()), {})

        with (
            patch("products.tasks.backend.awaiting_input.get_tasks_cache", return_value=cache),
            patch(
                "products.tasks.backend.push_dispatcher.notify_task_run_awaiting_input",
                side_effect=self._enqueue_successfully,
            ) as notify,
            time_machine.travel("2026-10-16T12:00:00Z", tick=False) as clock,
        ):
            self.assertTrue(dispatch_awaiting_input(task_run, request_id="request-1"))
            clock.shift(elapsed)
            dispatched = dispatch_awaiting_input(replay_run, request_id=request_id)

        self.assertEqual(dispatched, expected_pushes == 2)
        self.assertEqual(notify.call_count, expected_pushes)

    @parameterized.expand([("background", "request-1"), ("interactive", ""), ("interactive", "r" * 201)])
    def test_skips_without_interactive_permission_request(self, mode: str, request_id: str) -> None:
        with patch("products.tasks.backend.push_dispatcher.notify_task_run_awaiting_input") as notify:
            self.assertFalse(dispatch_awaiting_input(TaskRun(state={"mode": mode}), request_id=request_id))
        notify.assert_not_called()

    def test_request_burst_does_not_allocate_dedupe_keys(self) -> None:
        task_run = TaskRun(id=uuid4(), state={"mode": "interactive"})
        cache = LocMemCache(str(uuid4()), {})
        with (
            patch("products.tasks.backend.awaiting_input.get_tasks_cache", return_value=cache),
            patch(
                "products.tasks.backend.push_dispatcher.notify_task_run_awaiting_input",
                side_effect=self._enqueue_successfully,
            ) as notify,
            time_machine.travel("2026-10-20T12:00:00Z", tick=False),
        ):
            self.assertTrue(dispatch_awaiting_input(task_run, request_id="first"))
            for index in range(100):
                self.assertFalse(dispatch_awaiting_input(task_run, request_id=f"request-{index}"))
            self.assertTrue(cache.get(f"tasks:awaiting_input:cooldown:{task_run.id}"))
            self.assertTrue(cache.get(f"tasks:awaiting_input:v1:{task_run.id}:first"))
            self.assertEqual(
                cache.get_many([f"tasks:awaiting_input:v1:{task_run.id}:request-{index}" for index in range(100)]),
                {},
            )
        notify.assert_called_once()

    def test_cache_failure_does_not_fail_event_delivery(self) -> None:
        with (
            patch(
                "products.tasks.backend.awaiting_input.get_tasks_cache", side_effect=RuntimeError("cache unavailable")
            ),
            patch("products.tasks.backend.push_dispatcher.notify_task_run_awaiting_input") as notify,
        ):
            self.assertFalse(dispatch_awaiting_input(TaskRun(state={"mode": "interactive"}), request_id="request-1"))
        notify.assert_not_called()
