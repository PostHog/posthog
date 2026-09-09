import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.facade.api import update_task_run
from products.tasks.backend.logic.services.workflow_step_resume import (
    DEFERRED_RESUME_TASK,
    FINAL_MESSAGE_GRACE_SECONDS,
    resume_workflow_step_after_final_message,
    resume_workflow_step_for_run,
    resume_workflow_step_for_run_id,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import _persist_final_message

_RESUME = "products.tasks.backend.logic.services.workflow_step_resume.resume_workflow_step"
_SEND_TASK = "products.tasks.backend.logic.services.workflow_step_resume.current_app.send_task"


class TestResumeWorkflowStepForRun(BaseTest):
    def _run(
        self,
        *,
        origin_product: str = Task.OriginProduct.WORKFLOW,
        origin_key: str | None = "job:step:1",
        status: str = TaskRun.Status.COMPLETED,
        final_message: str | None = "Collected 3 PRs",
        json_schema: dict | None = None,
        structured_output: dict | None = None,
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin_product,
            origin_key=origin_key,
            hog_flow_id=uuid.uuid4() if origin_key else None,
            json_schema=json_schema,
        )
        output: dict = {"pr_url": "https://example.com/pr/1", **(structured_output or {})}
        if final_message is not None:
            output["final_message"] = final_message
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            output=output,
            error_message="boom" if status == TaskRun.Status.FAILED else None,
        )

    @parameterized.expand(
        [
            ("completed", TaskRun.Status.COMPLETED, "completed"),
            ("failed", TaskRun.Status.FAILED, "failed"),
            ("cancelled", TaskRun.Status.CANCELLED, "cancelled"),
        ]
    )
    def test_wakes_the_step_that_started_the_run(self, _name: str, run_status: str, expected: str) -> None:
        run = self._run(status=run_status)

        with patch(_RESUME) as resume, patch(_SEND_TASK) as send_task:
            resume_workflow_step_for_run(run)

        send_task.assert_not_called()
        resume.assert_called_once_with(
            team_id=self.team.id,
            origin_key="job:step:1",
            status=expected,
            result={
                "run_id": str(run.id),
                "output": None,
                "warnings": None,
                "final_message": "Collected 3 PRs",
                "pr_urls": ["https://example.com/pr/1"],
                "error_message": "boom" if run_status == TaskRun.Status.FAILED else None,
            },
        )

    _SCHEMA = {
        "type": "object",
        "properties": {"verdict": {"type": "string"}, "score": {"type": "number"}},
        "required": ["verdict", "score"],
    }

    @parameterized.expand(
        [
            ("matching_output", TaskRun.Status.COMPLETED, {"verdict": "ship", "score": 0.9}, None),
            (
                "missing_field",
                TaskRun.Status.COMPLETED,
                {"verdict": "ship"},
                [
                    "The task finished, but its output does not match the output variables: 'score' is a required property"
                ],
            ),
            ("failed_run_is_not_judged", TaskRun.Status.FAILED, {}, None),
        ]
    )
    def test_reports_the_agent_output_against_the_task_schema(
        self, _name: str, status: str, structured_output: dict, warnings: list[str] | None
    ) -> None:
        run = self._run(status=status, json_schema=self._SCHEMA, structured_output=structured_output)

        with patch(_RESUME) as resume:
            resume_workflow_step_for_run(run)

        result = resume.call_args.kwargs["result"]
        assert result["output"] == structured_output
        assert result["warnings"] == warnings
        assert resume.call_args.kwargs["status"] == ("failed" if status == TaskRun.Status.FAILED else "completed")

    @parameterized.expand(
        [
            ("not_from_a_workflow", Task.OriginProduct.USER_CREATED, None, TaskRun.Status.COMPLETED),
            ("workflow_task_without_a_key", Task.OriginProduct.WORKFLOW, None, TaskRun.Status.COMPLETED),
            ("run_still_in_progress", Task.OriginProduct.WORKFLOW, "job:step:1", TaskRun.Status.IN_PROGRESS),
        ]
    )
    def test_wakes_nothing_when(self, _name: str, origin_product: str, origin_key: str | None, status: str) -> None:
        run = self._run(origin_product=origin_product, origin_key=origin_key, status=status)

        with patch(_RESUME) as resume, patch(_SEND_TASK) as send_task:
            resume_workflow_step_for_run(run)
            resume_workflow_step_after_final_message(run)

        resume.assert_not_called()
        send_task.assert_not_called()

    def test_a_completed_run_without_its_final_message_defers_the_wake(self) -> None:
        run = self._run(final_message=None)

        with patch(_RESUME) as resume, patch(_SEND_TASK) as send_task:
            resume_workflow_step_for_run(run)

        resume.assert_not_called()
        send_task.assert_called_once_with(
            DEFERRED_RESUME_TASK, args=[str(run.id)], countdown=FINAL_MESSAGE_GRACE_SECONDS
        )

    def test_the_deferred_wake_fires_with_whatever_the_run_has_by_then(self) -> None:
        run = self._run(final_message=None)

        with patch(_RESUME) as resume, patch(_SEND_TASK) as send_task:
            resume_workflow_step_for_run_id(run.id)

        send_task.assert_not_called()
        assert resume.call_args.kwargs["result"]["final_message"] is None

    @parameterized.expand(
        [
            ("already_completed", TaskRun.Status.COMPLETED, True),
            ("still_running", TaskRun.Status.IN_PROGRESS, False),
        ]
    )
    def test_the_final_message_wakes_a_run_that_is(self, _name: str, status: str, wakes: bool) -> None:
        run = self._run(status=status)

        with patch(_RESUME) as resume:
            resume_workflow_step_after_final_message(run)

        assert resume.call_count == (1 if wakes else 0)
        if wakes:
            assert resume.call_args.kwargs["result"]["final_message"] == "Collected 3 PRs"

    def test_agent_completion_waits_for_the_current_turn_and_recovers_a_broker_failure(self) -> None:
        run = self._run(status=TaskRun.Status.IN_PROGRESS, final_message="Previous turn")
        run.state = {"end_run_when_done": True}
        run.save(update_fields=["state"])

        with (
            patch(_RESUME) as resume,
            patch(_SEND_TASK, side_effect=[RuntimeError("broker down"), None]) as send_task,
            patch("products.tasks.backend.facade.api.signal_workflow_completion"),
            patch("products.tasks.backend.logic.services.loop_runs.handle_loop_run_terminal") as bookkeeping,
        ):
            with pytest.raises(RuntimeError, match="broker down"):
                update_task_run(
                    run.id,
                    run.task_id,
                    self.team.id,
                    validated_data={"status": "completed"},
                    only_if_non_terminal=True,
                    caller_is_agent=True,
                )
            run.refresh_from_db()
            assert run.status == TaskRun.Status.COMPLETED
            assert run.output is not None
            assert "final_message" not in run.output
            assert run.output["pr_url"] == "https://example.com/pr/1"
            with self.captureOnCommitCallbacks(execute=True):
                update_task_run(
                    run.id,
                    run.task_id,
                    self.team.id,
                    validated_data={"status": "completed"},
                    only_if_non_terminal=True,
                    caller_is_agent=True,
                )
            assert send_task.call_count == 2
            bookkeeping.assert_called_once()
            resume.assert_not_called()
            _persist_final_message(str(run.id), "Current turn")
            assert resume.call_args.kwargs["result"]["final_message"] == "Current turn"
