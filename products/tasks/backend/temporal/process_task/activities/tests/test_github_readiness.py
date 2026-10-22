import inspect
from collections.abc import Callable
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.check_github_readiness import (
    check_self_driving_github_readiness,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.check_github_readiness"
check_readiness = cast(Callable[[str], str], inspect.unwrap(check_self_driving_github_readiness))


class TestImplementationGitHubReadiness(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        task = Task.objects.create(
            team=self.team, title="Example implementation", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        self.task_run = TaskRun.objects.create(
            team=self.team, task=task, status=TaskRun.Status.QUEUED, environment=TaskRun.Environment.CLOUD
        )

    def test_queued_implementation_waits_and_clears_the_blocker_when_ready(self) -> None:
        with patch(
            f"{MODULE}.get_team_github_readiness",
            return_value=GitHubReadiness(status=GitHubReadinessStatus.NOT_CONNECTED),
        ):
            self.assertEqual(check_readiness(str(self.task_run.id)), "blocked")
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.status, TaskRun.Status.QUEUED)
        self.assertEqual(self.task_run.state["github_blocked_reason"], "not_connected")
        with patch(
            f"{MODULE}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
        ):
            self.assertEqual(check_readiness(str(self.task_run.id)), "ready")
        self.task_run.refresh_from_db()
        self.assertNotIn("github_blocked_reason", self.task_run.state)
        self.assertIsNone(self.task_run.error_message)

    def test_cancelled_run_does_not_resume(self) -> None:
        self.task_run.status = TaskRun.Status.CANCELLED
        self.task_run.save(update_fields=["status"])
        with patch(f"{MODULE}.get_team_github_readiness") as readiness:
            self.assertEqual(check_readiness(str(self.task_run.id)), "cancelled")
        readiness.assert_not_called()

    def test_other_task_origins_are_unaffected(self) -> None:
        self.task_run.task.origin_product = Task.OriginProduct.USER_CREATED
        self.task_run.task.save(update_fields=["origin_product"])
        with patch(f"{MODULE}.get_team_github_readiness") as readiness:
            self.assertEqual(check_readiness(str(self.task_run.id)), "ready")
        readiness.assert_not_called()
