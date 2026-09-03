import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.logic.services.workflow_step_resume import (
    DEFERRED_RESUME_TASK,
    FINAL_MESSAGE_GRACE_SECONDS,
    resume_workflow_step_after_final_message,
    resume_workflow_step_for_run,
    resume_workflow_step_for_run_id,
)
from products.tasks.backend.models import Task, TaskRun

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
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin_product,
            origin_key=origin_key,
            hog_flow_id=uuid.uuid4() if origin_key else None,
        )
        output = {"pr_url": "https://example.com/pr/1"}
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
                "final_message": "Collected 3 PRs",
                "pr_urls": ["https://example.com/pr/1"],
                "error_message": "boom" if run_status == TaskRun.Status.FAILED else None,
            },
        )

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
