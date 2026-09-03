import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.logic.services.workflow_step_resume import resume_workflow_step_for_run
from products.tasks.backend.models import Task, TaskRun

_RESUME = "products.tasks.backend.logic.services.workflow_step_resume.resume_workflow_step"


class TestResumeWorkflowStepForRun(BaseTest):
    def _run(self, *, origin_product: str, origin_key: str | None, status: str) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin_product,
            origin_key=origin_key,
            hog_flow_id=uuid.uuid4() if origin_key else None,
        )
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            output={"final_message": "Collected 3 PRs", "pr_url": "https://example.com/pr/1"},
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
        run = self._run(origin_product=Task.OriginProduct.WORKFLOW, origin_key="job:step:1", status=run_status)

        with patch(_RESUME) as resume:
            resume_workflow_step_for_run(run)

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

        with patch(_RESUME) as resume:
            resume_workflow_step_for_run(run)

        resume.assert_not_called()
