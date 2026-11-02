import inspect
from collections.abc import Callable
from datetime import timedelta
from typing import cast

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.facade.github_recovery import _manual_implementation_may_resume
from products.signals.backend.models import SignalReport, SignalReportTask
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult
from products.tasks.backend.github_recovery import GitHubRecoveryCheck
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.check_github_readiness import (
    check_self_driving_github_readiness,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.check_github_readiness"
check_readiness = cast(Callable[[str], GitHubRecoveryCheck], inspect.unwrap(check_self_driving_github_readiness))


@time_machine.travel("2026-01-01T12:00:00Z", tick=False)
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
        assert task.signal_report_id is not None
        SignalReportTask.objects.create(
            team=self.team, report_id=task.signal_report_id, task=task, relationship="implementation"
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

    @parameterized.expand([False, True])
    def test_manual_recovery_revalidates_the_original_revision(self, revised: bool) -> None:
        from products.signals.backend.models import SignalReportArtefact

        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        task = self.task_run.task
        report = task.signal_report
        assert report is not None
        report.status = SignalReport.Status.READY
        report.run_count = 2
        report.save()
        SignalReportTask.objects.filter(task=task).delete()
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=RepoSelectionResult(repository=task.repository, reason="Selected target"),
            attribution=ArtefactAttribution.system(),
        )
        if revised:
            report.content_revision_count = 1
            report.save(update_fields=["content_revision_count"])
        with patch(
            "products.signals.backend.facade.github_recovery.self_driving_free_trial_enabled", return_value=False
        ):
            assert (
                _manual_implementation_may_resume(
                    self.team.id, str(report.id), str(task.id), self.user.id, "example/repo"
                )
                is not revised
            )

    @parameterized.expand(["user_created", "discussion"])
    def test_other_task_origins_are_unaffected(self, kind: str) -> None:
        if kind == "discussion":
            SignalReportTask.objects.filter(task=self.task_run.task).delete()
        else:
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
