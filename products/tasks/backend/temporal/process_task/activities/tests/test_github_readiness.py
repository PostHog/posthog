import inspect
from collections.abc import Callable
from datetime import timedelta
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus

from products.signals.backend.models import SignalReport
from products.tasks.backend.github_recovery import GitHubRecoveryCheck
from products.tasks.backend.github_recovery_tasks import resume_github_blocked_task_runs
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.check_github_readiness import (
    check_self_driving_github_readiness,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.check_github_readiness"
check_readiness = cast(Callable[[str], GitHubRecoveryCheck], inspect.unwrap(check_self_driving_github_readiness))


class TestImplementationGitHubReadiness(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        task = Task.objects.create(
            team=self.team,
            title="Example implementation",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report_id=SignalReport.objects.create(team=self.team).id,
            created_by=self.user,
            repository="example/repo",
        )
        self.task_run = TaskRun.objects.create(
            team=self.team, task=task, status=TaskRun.Status.QUEUED, environment=TaskRun.Environment.CLOUD
        )

    def test_queued_implementation_waits_and_clears_the_blocker_when_ready(self) -> None:
        with patch(
            f"{MODULE}.get_team_github_readiness",
            return_value=GitHubReadiness(status=GitHubReadinessStatus.NOT_CONNECTED),
        ):
            blocked = check_readiness(str(self.task_run.id))
            self.assertEqual(blocked.status, "suspended")
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.status, TaskRun.Status.QUEUED)
        self.assertEqual(self.task_run.state["github_blocked_reason"], "not_connected")
        integration = Integration.objects.create(
            team=self.team, kind="github", integration_id="456", repository_cache=[{"full_name": "example/repo"}]
        )
        github = GitHubIntegration(integration, source="test", priority=Priority.NORMAL)
        with (
            patch(
                f"{MODULE}.get_team_github_readiness",
                return_value=GitHubReadiness(status=GitHubReadinessStatus.READY, integration=github),
            ),
            patch(f"{MODULE}.implementation_may_resume", new_callable=AsyncMock, return_value=True),
        ):
            self.assertEqual(check_readiness(str(self.task_run.id)).status, "ready")
        self.task_run.refresh_from_db()
        self.assertNotIn("github_blocked_reason", self.task_run.state)
        self.assertNotIn("github_recovery_deadline", self.task_run.state)
        self.assertIsNone(self.task_run.error_message)
        self.assertEqual(self.task_run.task.github_integration_id, integration.id)

    def test_cancelled_run_does_not_resume(self) -> None:
        self.task_run.status = TaskRun.Status.CANCELLED
        self.task_run.save(update_fields=["status"])
        with patch(f"{MODULE}.get_team_github_readiness") as readiness:
            self.assertEqual(check_readiness(str(self.task_run.id)).status, "cancelled")
        readiness.assert_not_called()

    def test_other_task_origins_are_unaffected(self) -> None:
        self.task_run.task.origin_product = Task.OriginProduct.USER_CREATED
        self.task_run.task.save(update_fields=["origin_product"])
        with patch(f"{MODULE}.get_team_github_readiness") as readiness:
            self.assertEqual(check_readiness(str(self.task_run.id)).status, "ready")
        readiness.assert_not_called()

    @parameterized.expand([("expired",), ("ineligible",), ("temporary",)])
    def test_recovery_preserves_deadline_and_checks_current_eligibility(self, case: str) -> None:
        deadline = timezone.now() + timedelta(days=-1 if case == "expired" else 1)
        self.task_run.state = {
            "github_blocked_reason": "not_connected",
            "github_recovery_deadline": deadline.isoformat(),
        }
        self.task_run.save(update_fields=["state"])
        with (
            patch(
                f"{MODULE}.get_team_github_readiness",
                return_value=GitHubReadiness(
                    status=GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE
                    if case == "temporary"
                    else GitHubReadinessStatus.READY
                ),
            ) as readiness,
            patch(f"{MODULE}.implementation_may_resume", new_callable=AsyncMock, return_value=False) as eligible,
        ):
            result = check_readiness(str(self.task_run.id))
        self.assertEqual(result.status, {"expired": "expired", "ineligible": "cancelled", "temporary": "retry"}[case])
        self.assertEqual(readiness.call_count, int(case != "expired"))
        self.assertEqual(eligible.await_count, int(case == "ineligible"))
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state["github_recovery_deadline"], deadline.isoformat())

    def test_reconnect_signals_only_recent_suspended_implementations(self) -> None:
        self.task_run.state = {"github_recovery_deadline": (timezone.now() + timedelta(days=1)).isoformat()}
        self.task_run.save(update_fields=["state"])
        TaskRun.objects.create(
            team=self.team,
            task=self.task_run.task,
            status=TaskRun.Status.QUEUED,
            state={"github_recovery_deadline": (timezone.now() - timedelta(days=1)).isoformat()},
        )
        TaskRun.objects.create(team=self.team, task=self.task_run.task, status=TaskRun.Status.QUEUED)
        with patch(
            "products.tasks.backend.github_recovery_tasks._signal_github_recovery", new_callable=AsyncMock
        ) as signal:
            resume_github_blocked_task_runs(self.team.id)
        signal.assert_awaited_once_with(self.task_run.workflow_id)
