from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.signals.backend.scout_harness.trial_judge import TrialJudgeExecutionError, judge_trial_run
from products.signals.backend.test.test_scout_trial_judge import _snapshot, _verdict
from products.signals.backend.trial_judging_types import TrialJudgeVerdicts
from products.tasks.backend.models import Task, TaskRun

MODULE = "products.signals.backend.scout_harness.trial_judge"
SESSION_MODULE = "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner"


class TestSandboxJudgeLifecycle(SimpleTestCase):
    @parameterized.expand(["success", "invalid_result", "cancelled", "startup_failure", "cleanup_failure"])
    async def test_judge_closes_its_sandbox_and_does_not_disclose_errors(self, outcome: str) -> None:
        snapshot = _snapshot()
        evidence = snapshot.runs[0]
        run = SimpleNamespace(
            id=uuid4(), task_id=uuid4(), state={"token_usage": {"input_tokens": 123, "output_tokens": 45}}
        )
        session = SimpleNamespace(task_run=run, end=AsyncMock())
        if outcome == "cleanup_failure":
            session.end.side_effect = RuntimeError("private fixture content must not appear in errors")
        output = TrialJudgeVerdicts.model_validate({"summary": "Synthetic assessment.", "criteria": [_verdict()]})
        if outcome == "invalid_result":
            output = output.model_copy(update={"criteria": output.criteria * 2})

        async def start(**kwargs):
            kwargs["before_task_dispatch"](run.id)
            if outcome == "cancelled":
                raise asyncio.CancelledError
            if outcome == "startup_failure":
                raise RuntimeError("private fixture content must not appear in errors")
            return session, output

        with (
            patch(f"{MODULE}._assert_scout_available"),
            patch(f"{MODULE}.read_trial_evidence_sources", return_value=evidence.sources),
            patch(f"{MODULE}.tasks_facade.get_task_by_origin_key", return_value=None),
            patch(f"{MODULE}.get_or_create_signals_sandbox_env", return_value=str(uuid4())),
            patch(f"{MODULE}.tasks_facade.attach_task_run_input_files"),
            patch(f"{MODULE}.tasks_facade.get_task_run", return_value=run),
            patch(f"{MODULE}.tasks_facade.update_task_run") as update_run,
            patch(f"{MODULE}.MultiTurnSession.start", side_effect=start),
        ):
            if outcome == "success":
                result = await judge_trial_run(snapshot, evidence)
                self.assertEqual(result.status, "judged")
                self.assertEqual((result.input_tokens, result.output_tokens), (123, 45))
                self.assertEqual(result.criteria[0].verdict, "pass")
                session.end.assert_awaited_once_with(status="completed", error=None)
                update_run.assert_not_called()
            elif outcome == "cancelled":
                with self.assertRaises(asyncio.CancelledError):
                    await judge_trial_run(snapshot, evidence)
                self.assertEqual(update_run.call_args.kwargs["validated_data"]["status"], "failed")
            else:
                with self.assertRaises(TrialJudgeExecutionError) as error:
                    await judge_trial_run(snapshot, evidence)
                self.assertNotIn("private fixture content", str(error.exception))
                self.assertEqual(update_run.call_args.kwargs["validated_data"]["status"], "failed")
                if outcome == "invalid_result":
                    self.assertEqual(session.end.call_args.kwargs["status"], "failed")

    @parameterized.expand(["missing_evidence", "existing_judge"])
    async def test_unavailable_input_and_existing_judge_do_not_start_a_paid_run(self, failure: str) -> None:
        snapshot = _snapshot()
        with (
            patch(f"{MODULE}._assert_scout_available"),
            patch(
                f"{MODULE}.read_trial_evidence_sources",
                side_effect=ValueError("private missing file") if failure == "missing_evidence" else None,
                return_value=snapshot.runs[0].sources,
            ),
            patch(f"{MODULE}.tasks_facade.get_task_by_origin_key", return_value=object()),
            patch(f"{MODULE}.MultiTurnSession.start", new_callable=AsyncMock) as start,
        ):
            with self.assertRaises(TrialJudgeExecutionError):
                await judge_trial_run(snapshot, snapshot.runs[0])
        start.assert_not_awaited()


class TestSandboxJudgeDispatch(BaseTest):
    @parameterized.expand([("valid_json", False), ("invalid_json", True)])
    @override_settings(DEBUG=False)
    def test_ordinary_task_attaches_evidence_and_retries_json_in_same_run(self, _name: str, retry_json: bool) -> None:
        snapshot = _snapshot().model_copy(update={"team_id": self.team.id, "user_id": self.user.id})
        evidence = snapshot.runs[0]
        output = TrialJudgeVerdicts.model_validate({"summary": "Synthetic assessment.", "criteria": [_verdict()]})
        dispatched: list[TaskRun] = []
        log_lines: list[str] = []
        followup_messages: list[str] = []

        def append_response(text: str) -> None:
            log_lines.extend(
                [
                    json.dumps(
                        {
                            "notification": {
                                "method": "session/update",
                                "params": {
                                    "update": {
                                        "sessionUpdate": "agent_message",
                                        "content": {"type": "text", "text": text},
                                    }
                                },
                            }
                        }
                    ),
                    json.dumps({"notification": {"result": {"stopReason": "end_turn"}}}),
                ]
            )

        append_response("The synthetic check passed." if retry_json else output.model_dump_json())

        async def signal(signal: object, message: str | None = None, **_kwargs: object) -> None:
            if message is not None:
                followup_messages.append(message)
                self.assertIn("Return the complete JSON object", message)
                append_response(output.model_dump_json())

        workflow_handle = MagicMock(signal=AsyncMock(side_effect=signal))
        client = MagicMock()
        client.get_workflow_handle.return_value = workflow_handle

        def dispatch(run: TaskRun, **_kwargs: object) -> None:
            run.refresh_from_db()
            self.assertEqual(run.task.origin_product, Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS)
            self.assertFalse(run.task.is_scout_experiment)
            self.assertNotIn("scout_trial_judge", run.state)
            self.assertEqual(run.state["pending_dispatch"]["posthog_mcp_scopes"], [])
            self.assertEqual(run.state["pending_user_message_id"], str(run.id))
            self.assertEqual(run.state["pending_user_artifact_ids"], [item["id"] for item in run.artifacts])
            self.assertEqual([item["name"] for item in run.artifacts], [file.filename for file in evidence.files])
            self.assertNotIn(evidence.sources[0].text, run.state["pending_user_message"])
            self.assertEqual(run.state["model"], snapshot.judge_model)
            self.assertEqual(run.state["reasoning_effort"], "high")
            self.assertEqual(run.state["mcp_gateway_server_ids"], [])
            self.assertEqual(run.task.mcp_builtin_agent_key, "scout")
            self.assertEqual(run.task.mcp_gateway_server_allowlist, [])
            self.assertIsNone(run.task.repository)
            self.assertTrue(run.task.internal)
            for artifact in run.artifacts:
                self.assertIn(f"/{snapshot.team_id}/evaluations/{snapshot.evaluation_id}/", artifact["storage_path"])
                self.assertIn(str(evidence.launch_id), artifact["storage_path"])

            dispatched.append(run)

        with (
            team_scope(self.team.id, canonical=True),
            patch(f"{MODULE}._assert_scout_available"),
            patch(f"{MODULE}.read_trial_evidence_sources", return_value=evidence.sources),
            patch("posthoganalytics.feature_enabled", return_value=False),
            patch(
                "products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow",
                side_effect=dispatch,
            ),
            patch(f"{SESSION_MODULE}.async_connect", new=AsyncMock(return_value=client)),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("posthog.storage.object_storage.read", side_effect=lambda *_args, **_kwargs: "\n".join(log_lines)),
        ):
            result = async_to_sync(judge_trial_run)(snapshot, evidence)
            self.assertEqual(result.status, "judged")
            self.assertEqual(len(dispatched), 1)
            with self.assertRaisesMessage(TrialJudgeExecutionError, "already has a judge task"):
                async_to_sync(judge_trial_run)(snapshot, evidence)
            self.assertEqual(
                Task.objects.filter(team_id=self.team.id, origin_key__startswith="scout-trial-judge:").count(), 1
            )
            self.assertEqual(TaskRun.objects.filter(team_id=self.team.id, task=dispatched[0].task).count(), 1)
            self.assertEqual(workflow_handle.signal.call_args.kwargs["args"], ["completed", None])
            self.assertEqual(result.criteria[0].verdict, "pass")
            self.assertEqual(len(followup_messages), int(retry_json))
