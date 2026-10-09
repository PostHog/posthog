from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.signals.backend.scout_harness.trial_evaluation import TrialEvaluationError
from products.signals.backend.scout_harness.trial_judge import TrialJudgeExecutionError, judge_trial_run
from products.signals.backend.scout_harness.trial_launch import ScoutTrialsDisabled
from products.signals.backend.test.test_scout_trial_judge import _criterion, _snapshot, _verdict
from products.signals.backend.trial_judging_types import TrialJudgeVerdicts
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Task, TaskRun

MODULE = "products.signals.backend.scout_harness.trial_judge"
DISPATCH = "products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow"


@override_settings(DEBUG=False)
class TestSandboxJudgeDispatch(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.snapshot = _snapshot().model_copy(update={"team_id": self.team.id, "user_id": self.user.id})
        self.evidence = self.snapshot.runs[0]
        self.output = TrialJudgeVerdicts.model_validate({"summary": "Synthetic assessment.", "criteria": [_verdict()]})
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.enterContext(patch(f"{MODULE}._assert_scout_available"))
        self.read_sources = self.enterContext(
            patch(f"{MODULE}.read_trial_evidence_sources", return_value=self.evidence.sources)
        )
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=False))
        self.trials_enabled = self.enterContext(
            patch("products.signals.backend.scout_harness.trial_launch.scout_trials_enabled", return_value=True)
        )
        self.dispatch = self.enterContext(patch(DISPATCH))

    @parameterized.expand([("poll_completed", False), ("worker_interrupted", True), ("origin_race", False)])
    def test_ordinary_task_resumes_and_collects_complete_saved_output(self, scenario: str, interrupted: bool) -> None:
        criteria = [_criterion(f"check-{index}") for index in range(14)]
        snapshot = self.snapshot.model_copy(update={"criteria": criteria})
        output = TrialJudgeVerdicts.model_validate(
            {
                "summary": "Synthetic assessment.",
                "criteria": [
                    {
                        **_verdict(identifier=criterion.id),
                        "reason": "The synthetic observation supports this check. " * 38,
                    }
                    for criterion in criteria
                ],
            }
        )
        self.assertGreater(len(output.model_dump_json()), 20_000)

        def dispatch(run: TaskRun, **_kwargs: object) -> None:
            run.refresh_from_db()
            self.assertEqual(run.task.origin_product, Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS)
            self.assertFalse(run.task.is_scout_experiment)
            self.assertNotIn("scout_trial_judge", run.state)
            self.assertNotIn("caller_ends_run", run.state)
            self.assertEqual(run.task.json_schema, TrialJudgeVerdicts.model_json_schema())
            self.assertEqual(run.state["pending_dispatch"]["posthog_mcp_scopes"], [])
            self.assertFalse(run.state["pending_dispatch"]["create_pr"])
            self.assertEqual(run.state["pending_user_message_id"], str(run.id))
            self.assertEqual(run.state["pending_user_artifact_ids"], [item["id"] for item in run.artifacts])
            self.assertEqual([item["name"] for item in run.artifacts], [file.filename for file in self.evidence.files])
            self.assertNotIn(self.evidence.sources[0].text, run.state["pending_user_message"])
            self.assertEqual(run.state["model"], snapshot.judge_model)
            self.assertEqual(run.state["reasoning_effort"], "high")
            self.assertEqual(run.state["mcp_gateway_server_ids"], [])
            self.assertFalse(run.state["include_live_context"])
            self.assertEqual(run.task.mcp_builtin_agent_key, "scout")
            self.assertEqual(run.task.mcp_gateway_server_allowlist, [])
            self.assertIsNone(run.task.repository)
            self.assertIsNone(run.task.github_integration_id)
            self.assertIsNone(run.task.github_user_integration_id)
            self.assertTrue(run.task.internal)
            for artifact in run.artifacts:
                self.assertIn(f"/{snapshot.team_id}/evaluations/{snapshot.evaluation_id}/", artifact["storage_path"])
                self.assertIn(str(self.evidence.launch_id), artifact["storage_path"])

        self.dispatch.side_effect = dispatch
        create_and_run_task = tasks_facade.create_and_run_task

        def interrupted_create(**kwargs: object) -> None:
            create_and_run_task(**kwargs)
            raise asyncio.CancelledError

        if interrupted:
            with (
                patch(f"{MODULE}.tasks_facade.create_and_run_task", side_effect=interrupted_create),
                self.assertRaises(asyncio.CancelledError),
            ):
                async_to_sync(judge_trial_run)(snapshot, self.evidence)
        else:
            self.assertIsNone(async_to_sync(judge_trial_run)(snapshot, self.evidence))

        run = TaskRun.objects.get(team_id=self.team.id, task__origin_key__startswith="scout-trial-judge:")
        self.assertFalse(run.is_terminal)
        if scenario == "origin_race":
            existing = tasks_facade.get_task_by_origin_key(self.team.id, run.task.origin_key)
            with patch(f"{MODULE}.tasks_facade.get_task_by_origin_key", side_effect=[None, existing]):
                self.assertIsNone(async_to_sync(judge_trial_run)(snapshot, self.evidence))
        self.trials_enabled.return_value = False
        self.assertIsNone(async_to_sync(judge_trial_run)(snapshot, self.evidence))
        handle = MagicMock(signal=AsyncMock())
        client = MagicMock()
        client.get_workflow_handle.return_value = handle
        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            saved = tasks_facade.set_task_run_output(
                run.id, run.task_id, self.team.id, output=output.model_dump(mode="json")
            )
        assert saved is not None
        self.assertEqual(saved.output, output.model_dump(mode="json"))
        self.assertEqual(handle.signal.call_args.kwargs["args"], ["completed", None])
        self.assertIsNone(async_to_sync(judge_trial_run)(snapshot, self.evidence))
        tasks_facade.update_task_run(
            run.id,
            run.task_id,
            self.team.id,
            validated_data={
                "status": "completed",
                "output": {"final_message": '"criteria":[]}'},
                "state": {"token_usage": {"input_tokens": 123, "output_tokens": 45}},
            },
        )

        result = async_to_sync(judge_trial_run)(snapshot, self.evidence)
        assert result is not None
        self.assertEqual(result.status, "judged")
        self.assertEqual(result.criteria, output.criteria)
        self.assertEqual((result.input_tokens, result.output_tokens), (123, 45))
        self.assertEqual(
            Task.objects.filter(team_id=self.team.id, origin_key__startswith="scout-trial-judge:").count(), 1
        )
        self.assertEqual(TaskRun.objects.filter(team_id=self.team.id, task=run.task).count(), 1)
        self.dispatch.assert_called_once()

    @parameterized.expand([("no_output", False), ("output_saved_without_completion", True)])
    @time_machine.travel("2026-08-01T12:00:00Z", tick=False)
    def test_resumed_judge_keeps_its_original_deadline(self, _name: str, output_saved: bool) -> None:
        self.assertIsNone(async_to_sync(judge_trial_run)(self.snapshot, self.evidence))
        run = TaskRun.objects.get(team_id=self.team.id, task__origin_key__startswith="scout-trial-judge:")
        started_at = datetime.now(UTC)
        with time_machine.travel(started_at + timedelta(minutes=29), tick=False):
            self.assertIsNone(async_to_sync(judge_trial_run)(self.snapshot, self.evidence))
        if output_saved:
            with patch("posthog.temporal.common.client.sync_connect", side_effect=RuntimeError):
                tasks_facade.set_task_run_output(
                    run.id, run.task_id, self.team.id, output=self.output.model_dump(mode="json")
                )
        with time_machine.travel(started_at + timedelta(minutes=31), tick=False):
            if output_saved:
                result = async_to_sync(judge_trial_run)(self.snapshot, self.evidence)
                assert result is not None
                self.assertEqual((result.status, result.criteria), ("judged", self.output.criteria))
            else:
                with self.assertRaises(TrialJudgeExecutionError):
                    async_to_sync(judge_trial_run)(self.snapshot, self.evidence)
        run.refresh_from_db()
        if output_saved:
            self.assertFalse(run.is_terminal)
        else:
            self.assertEqual(run.status, TaskRun.Status.FAILED)
            self.assertIn("did not finish", run.error_message)
        self.dispatch.assert_called_once()

    @parameterized.expand(["failed", "cancelled", "invalid_result", "missing_result"])
    def test_terminal_failure_is_not_judged_or_restarted(self, outcome: str) -> None:
        self.assertIsNone(async_to_sync(judge_trial_run)(self.snapshot, self.evidence))
        run = TaskRun.objects.get(team_id=self.team.id, task__origin_key__startswith="scout-trial-judge:")
        run.status = outcome if outcome in {"failed", "cancelled"} else TaskRun.Status.COMPLETED
        run.error_message = "private fixture content must not appear in errors"
        run.output = self.output.model_dump(mode="json")
        if outcome == "invalid_result":
            run.output["criteria"] *= 2
        elif outcome == "missing_result":
            run.output = {"final_message": "private fixture content must not appear in errors"}
        run.save(update_fields=["status", "output", "error_message"])

        with self.assertRaises(TrialJudgeExecutionError) as error:
            async_to_sync(judge_trial_run)(self.snapshot, self.evidence)
        self.assertNotIn("private fixture content", str(error.exception))
        self.dispatch.assert_called_once()

    @parameterized.expand(["missing_evidence", "disabled"])
    def test_unavailable_input_or_disabled_trials_do_not_start_a_paid_run(self, reason: str) -> None:
        if reason == "missing_evidence":
            self.read_sources.side_effect = TrialEvaluationError("The saved evidence file is unavailable.")
        else:
            self.trials_enabled.return_value = False
        with self.assertRaises(TrialJudgeExecutionError if reason == "missing_evidence" else ScoutTrialsDisabled):
            async_to_sync(judge_trial_run)(self.snapshot, self.evidence)
        self.assertFalse(
            Task.objects.filter(team_id=self.team.id, origin_key__startswith="scout-trial-judge:").exists()
        )
        self.dispatch.assert_not_called()
