"""The push activity as Temporal runs it: an async activity whose body runs on a worker thread.

Calling `run_push` directly cannot show whether its heartbeats reach Temporal, because an async activity accepts a
heartbeat only on its event loop. These run the real activity in Temporal's activity test environment, so the
database rows the worker thread reads must be committed, hence a transactional test case.
"""

from __future__ import annotations

import threading
import dataclasses
from datetime import timedelta
from typing import Any

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from rest_framework import status
from temporalio.testing import ActivityEnvironment

from products.stacks.backend.models import StackDiff
from products.stacks.backend.temporal import activities
from products.stacks.backend.temporal.types import StackRunInput
from products.stacks.backend.tests.base import StackCalls, resource
from products.stacks.backend.tests.conftest import PRODUCT_DATABASES

WAIT_SECONDS = 5


class TestPushActivity(StackCalls, NonAtomicAPIBaseTest):
    # A transactional test empties the database after each test, so its data is set up per test too.
    CLASS_DATA_LEVEL_SETUP = False
    databases = PRODUCT_DATABASES

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, *, team: Any = None, **extra: Any):
        # Outside a test transaction, a commit callback runs at once.
        return getattr(self.client, method)(self.url(path, team), body or {}, format="json", **extra)

    def _run_activity(self, diff_id: str, on_heartbeat: Any) -> int:
        """Run the push activity, and return the id of the thread its event loop ran on."""
        diff = StackDiff.all_teams.using("stacks_db_writer").get(id=diff_id)
        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, heartbeat_timeout=timedelta(seconds=30))
        env.on_heartbeat = on_heartbeat
        run_input = StackRunInput(team_id=diff.team_id, diff_id=diff_id, attempt_id=str(diff.push_attempt_id))

        async def run() -> int:
            await env.run(activities.push_stack_diff, run_input)
            return threading.get_ident()

        with patch("products.stacks.backend.logic.lease.HEARTBEAT", timedelta(milliseconds=20)):
            return async_to_sync(run)()

    def _pushed_diff(self, resources: list[dict]) -> str:
        diff = self.ready_diff(resources)
        assert self.push(diff["id"]).status_code == status.HTTP_202_ACCEPTED
        return diff["id"]

    def test_heartbeats_reach_temporal_on_its_event_loop_while_the_engine_runs(self) -> None:
        diff_id = self._pushed_diff([resource("insight", "a")])
        threads: list[int] = []
        seen = threading.Event()

        def record(*details: Any) -> None:
            threads.append(threading.get_ident())
            if len(threads) >= 3:
                seen.set()

        engine_threads: list[int] = []

        def work_until_three_heartbeats(index: int) -> None:
            # The engine keeps working until three heartbeats arrived, so the loop kept beating past the first.
            engine_threads.append(threading.get_ident())
            seen.wait(WAIT_SECONDS)

        self.engine.on_each_record = work_until_three_heartbeats
        loop_thread = self._run_activity(diff_id, record)

        assert seen.is_set()
        # Every heartbeat was sent from the event loop's thread, never from a worker thread.
        assert set(threads) == {loop_thread}
        assert loop_thread not in engine_threads
        assert self.get_diff(diff_id)["status"] == "pushed"

    def test_a_heartbeat_temporal_refuses_stops_the_engine(self) -> None:
        diff_id = self._pushed_diff([resource("insight", "a"), resource("insight", "b"), resource("insight", "c")])
        refused = threading.Event()

        def refuse(*details: Any) -> None:
            refused.set()
            raise RuntimeError("activity no longer running")

        def wait_for_the_refusal(index: int) -> None:
            if index == 1:
                refused.wait(WAIT_SECONDS)
                # Let the heartbeat thread note the refusal before the engine reaches its next checkpoint.
                threading.Event().wait(0.2)

        self.engine.on_each_record = wait_for_the_refusal
        self._run_activity(diff_id, refuse)

        assert refused.is_set()
        # The engine stops at a checkpoint after the refusal, before it reaches the last change.
        assert len(self.engine.remote.of("insight")) < 3
        assert self.get_diff(diff_id)["push_status"] == "uncertain"
