import json
import asyncio
from types import SimpleNamespace
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.limits import TRIAL_ACTIVITY_TIMEOUT_S, TRIAL_MAX_RUNTIME_S
from products.tasks.backend.facade.agents import poll_for_turn
from products.tasks.backend.facade.contracts import AgentTaskRunDTO


class TestScoutTrialPollBudget(SimpleTestCase):
    @parameterized.expand([0.4, 1.0])
    async def test_trial_deadline_leaves_time_for_io_and_final_salvage(self, read_seconds: float) -> None:
        task_run = AgentTaskRunDTO(task_id=uuid4(), run_id=uuid4(), team_id=2, workflow_id="synthetic-trial")
        run = SimpleNamespace(
            id=task_run.run_id, log_url="synthetic-trial-log", status="in_progress", error_message=None
        )
        updates = [
            {"sessionUpdate": "agent_message", "content": {"type": "text", "text": "Synthetic final assessment."}},
            {"sessionUpdate": "usage_update", "used": 1000, "cost": None},
        ]
        log = "\n".join(
            json.dumps({"notification": {"method": "session/update", "params": {"update": update}}})
            for update in updates
        )
        loop = asyncio.get_running_loop()
        clock = SimpleNamespace(now=loop.time())
        original_sleep = asyncio.sleep
        sleeps = 0

        async def sleep(seconds: float) -> None:
            nonlocal sleeps
            sleeps += 1
            clock.now += seconds
            await original_sleep(0)

        def read_log(*_args: object, **_kwargs: object) -> str:
            clock.now += read_seconds
            return log

        with (
            patch.object(loop, "time", side_effect=lambda: clock.now),
            patch.object(loop, "slow_callback_duration", float("inf")),
            patch("asyncio.sleep", side_effect=sleep),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=run),
            patch("posthog.storage.object_storage.read", side_effect=read_log) as read,
        ):
            with self.assertRaises(TimeoutError):
                async with asyncio.timeout(31 * 60):
                    await asyncio.sleep(60)
                    await poll_for_turn(task_run, max_poll_seconds=TRIAL_MAX_RUNTIME_S)
            self.assertLess(sleeps, 180)
            sleeps = 0
            read.reset_mock()
            async with asyncio.timeout(TRIAL_ACTIVITY_TIMEOUT_S):
                await asyncio.sleep(60)
                result = await poll_for_turn(task_run, max_poll_seconds=TRIAL_MAX_RUNTIME_S)
                await asyncio.sleep(30)
            self.assertEqual(result.last_message, "Synthetic final assessment.")
            self.assertEqual(result.total_lines, 2)
            self.assertEqual(read.call_count, 181)
