from __future__ import annotations

import json
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.runner import WorkflowCleanupError
from products.signals.backend.constants import FIRST_REPORT_SCOUT
from products.signals.backend.first_report_scout_types import FirstReportScoutResult
from products.signals.backend.models import SignalScoutRun
from products.signals.evals import scout_runner
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.models import Task, TaskRun


class TestScoutEvalCleanup(IsolatedAsyncioTestCase):
    @parameterized.expand([("agent_message",), ("agent_message_chunk",)])
    def test_progress_time_uses_first_text_not_prior_tool_call(self, message_kind: str) -> None:
        started = datetime(2026, 1, 1, tzinfo=UTC)
        log = "invalid JSON\n" + "\n".join(
            json.dumps(
                {
                    "timestamp": (started + timedelta(seconds=seconds)).isoformat(),
                    "notification": {
                        "params": {
                            "update": {"sessionUpdate": kind, "content": {"type": "text", "text": "Investigating"}}
                        }
                    },
                }
            )
            for seconds, kind in [(10, "tool_call"), (20, message_kind), (30, message_kind)]
        )
        self.assertEqual(scout_runner.first_progress_seconds(log, started), 20)

    @parameterized.expand(
        [
            (None, True),
            (RuntimeError("Scout failed"), False),
            (asyncio.CancelledError(), False),
            (None, False),
            (None, True, "connect"),
            (None, True, "finish"),
            (None, True, None, True),
        ]
    )
    async def test_scout_reclaims_sandbox_and_preserves_failure(
        self,
        error: BaseException | None,
        cleanup_confirmed: bool,
        cancel_during: str | None = None,
        report_created: bool = False,
    ) -> None:
        task = SimpleNamespace(id="run", task_id="task", workflow_id="workflow")
        client = MagicMock()
        provider = MagicMock()
        result = SimpleNamespace(status="completed", run_id="scout", last_message=None)
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        workflow_finished = asyncio.Event()

        async def connect() -> MagicMock:
            if cancel_during == "connect":
                cleanup_started.set()
                await release_cleanup.wait()
            return client

        async def finish(*args: object, **kwargs: object) -> bool:
            if cancel_during == "finish":
                cleanup_started.set()
                await release_cleanup.wait()
            workflow_finished.set()
            return cleanup_confirmed

        with (
            patch.object(scout_runner, "prepare_scout", return_value="Server inventory"),
            patch.object(scout_runner, "latest_scout_task", return_value=task),
            patch.object(scout_runner, "arun_signals_scout", AsyncMock(return_value=result, side_effect=error)),
            patch.object(scout_runner.tasks_api, "read_task_run_conversation_logs", return_value=""),
            patch.object(
                scout_runner,
                "first_report_state",
                return_value={"status": "report_created" if report_created else "insufficient_data"},
            ),
            patch.object(
                scout_runner,
                "collect_closeout",
                return_value=FirstReportScoutResult(
                    outcome="insufficient_data",
                    missing_data=["More cohorts"],
                    checked_products=["product_analytics"],
                ),
            ),
            patch.object(
                scout_runner,
                "collect_reports",
                return_value=[
                    scout_runner.EvalReport(
                        id="report",
                        title="Upload failure",
                        summary="Check the upload handler.",
                        status="ready",
                        visible_after_seconds=20,
                    )
                ]
                if report_created
                else [],
            ),
            patch.object(scout_runner, "async_connect", connect),
            patch.object(scout_runner, "_finish_workflow", finish),
        ):
            invocation = scout_runner.run_first_report_scout(
                SandboxedEvalCase(name="sparse", prompt="Run the scout"),
                CustomPromptSandboxContext(team_id=1, user_id=2),
                provider=provider,
                on_cleanup=AsyncMock(side_effect=BrokenPipeError("Reporter disconnected")),
            )
            if cancel_during is not None:
                running = asyncio.create_task(invocation)
                await cleanup_started.wait()
                provider.cleanup_case.assert_not_called()
                running.cancel()
                release_cleanup.set()
                with self.assertRaises(asyncio.CancelledError):
                    await running
            elif error is not None:
                with self.assertRaises(type(error)) as raised:
                    await invocation
                self.assertIs(raised.exception, error)
            elif not cleanup_confirmed:
                with self.assertRaises(WorkflowCleanupError):
                    await invocation
            else:
                completed = await invocation
                self.assertEqual(completed.artifacts.model_dump()["missing_data"], ["More cohorts"])
                self.assertEqual(completed.artifacts.model_dump()["checked_products"], ["product_analytics"])
                self.assertEqual(
                    completed.artifacts.model_dump()["outcome"],
                    "report_created" if report_created else "insufficient_data",
                )
        self.assertTrue(workflow_finished.is_set())
        provider.cleanup_case.assert_called_once_with("task")


class TestScoutEvalCloseout(BaseTest):
    @parameterized.expand([("report_created",), ("insufficient_data",), (None,)])
    def test_collects_persisted_closeout(self, outcome: str | None) -> None:
        task = Task.objects.create(team=self.team, title="First investigation")
        task_run = TaskRun.objects.create(team=self.team, task=task, status="completed")
        closeout = {"outcome": outcome, "checked_products": ["product_analytics"], "missing_data": ["More cohorts"]}
        run = SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=task_run,
            skill_name=FIRST_REPORT_SCOUT,
            skill_version=1,
            metadata={"first_report_result": closeout} if outcome else {},
        )
        result = scout_runner.collect_closeout(self.team.id, str(run.id))
        if outcome is None:
            assert result is None
        else:
            assert result is not None
            assert result.model_dump() == closeout
