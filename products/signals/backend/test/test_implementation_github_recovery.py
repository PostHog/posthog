from datetime import timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.egress.limiter.policies import Priority
from posthog.models import OrganizationMembership
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.github_recovery import GITHUB_ACCESS_FAILURE
from products.signals.backend.implementation_github_recovery import (
    require_implementation_github_access,
    retry_report_implementation,
)
from products.signals.backend.implementation_github_recovery_tasks import retry_github_blocked_implementations
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult
from products.tasks.backend.facade.task_run_signals import TaskRunPreflightError, check_task_run_preflight
from products.tasks.backend.models import Task, TaskRun

MODULE = "products.signals.backend.implementation_github_recovery"


@time_machine.travel("2026-11-01T12:00:00Z", tick=False)
class TestImplementationGitHubRecovery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Example implementation", summary="Example evidence"
        )
        self.task = Task.objects.create(
            team=self.team,
            title="Example implementation",
            description="Example evidence",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report_id=self.report.id,
            created_by=self.user,
            repository="example/repo",
        )
        record_implementation_task(team_id=self.team.id, report_id=str(self.report.id), task_id=str(self.task.id))
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=RepoSelectionResult(repository=self.task.repository, reason="Selected target"),
            attribution=ArtefactAttribution.system(),
        )
        self.task_run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status=TaskRun.Status.QUEUED,
            environment=TaskRun.Environment.CLOUD,
            state={"run_source": "signal_report", "pr_authorship_mode": "bot", "pr_base_branch": "release"},
        )
        TaskRun.objects.filter(id=self.task_run.id).update(created_at=timezone.now() - timedelta(seconds=1))
        self.integration = Integration.objects.create(team=self.team, kind="github", integration_id="123")
        ready = GitHubReadiness(
            status=GitHubReadinessStatus.READY,
            integration=GitHubIntegration(self.integration, source="test", priority=Priority.NORMAL),
        )
        self.readiness = self.enterContext(patch(f"{MODULE}.get_team_github_readiness", return_value=ready))
        self.enterContext(patch(f"{MODULE}.self_driving_free_trial_enabled", return_value=False))
        self.source_privacy = self.enterContext(patch(f"{MODULE}.monitoring_repository_allowed", return_value=True))
        self.dispatch = self.enterContext(
            patch("products.tasks.backend.facade.api._trigger_task_processing_workflow", return_value=None)
        )

    def _block(self) -> None:
        ready = self.readiness.return_value
        self.readiness.return_value = GitHubReadiness(status=GitHubReadinessStatus.NOT_CONNECTED)
        with pytest.raises(TaskRunPreflightError):
            require_implementation_github_access(str(self.task_run.id), True)
        self.readiness.return_value = ready
        self.task_run.refresh_from_db()

    def _fail(self) -> None:
        self.task_run.status = TaskRun.Status.FAILED
        self.task_run.state = {**self.task_run.state, "failure_error_type": GITHUB_ACCESS_FAILURE}
        self.task_run.save(update_fields=["status", "state"])

    def test_preflight_refuses_access_before_starting_a_sandbox(self) -> None:
        self.readiness.return_value = GitHubReadiness(status=GitHubReadinessStatus.NOT_CONNECTED)
        with pytest.raises(TaskRunPreflightError) as error:
            check_task_run_preflight(str(self.task_run.id), True)
        assert error.value.reason == GITHUB_ACCESS_FAILURE
        self.report.refresh_from_db()
        assert self.report.implementation_blocked_reason == "not_connected"

    @parameterized.expand(["fresh", "expired_earlier_blocker", "recent_earlier_blocker", "no_named_selection"])
    def test_reconnect_creates_one_new_run_on_the_same_task(self, case: str) -> None:
        if case == "expired_earlier_blocker":
            SignalReport.objects.filter(id=self.report.id).update(
                implementation_blocked_reason="not_connected",
                implementation_blocked_at=timezone.now() - timedelta(days=8),
            )
        elif case == "recent_earlier_blocker":
            SignalReport.objects.filter(id=self.report.id).update(
                implementation_blocked_reason="not_connected",
                implementation_blocked_at=timezone.now() - timedelta(days=6),
            )
        elif case == "no_named_selection":
            SignalReportArtefact.objects.filter(report=self.report, type="repo_selection").delete()
        self.task_run.state = {**self.task_run.state, "pending_user_message": "Implement the fix."}
        self.task_run.save(update_fields=["state"])
        self._block()
        self._fail()
        # The earlier blocker leaves the sweep's window here, while this attempt's deadline is still ahead.
        retry_at = timezone.now() + timedelta(days=3 if case == "recent_earlier_blocker" else 0)
        with time_machine.travel(retry_at, tick=False):
            retry_github_blocked_implementations(self.team.id)
            retry_github_blocked_implementations(self.team.id)
        runs = list(self.task.runs.order_by("created_at", "id"))
        assert len(runs) == 2
        previous = next(run for run in runs if run.id == self.task_run.id)
        replacement = next(run for run in runs if run.id != self.task_run.id)
        assert previous.status == TaskRun.Status.FAILED
        assert replacement.status == TaskRun.Status.QUEUED
        assert replacement.state["resume_from_run_id"] == str(previous.id)
        assert replacement.state["github_recovery_deadline"] == previous.state["github_recovery_deadline"]
        assert replacement.state["pr_base_branch"] == "release"
        assert replacement.state["pending_user_message"] == "Implement the fix."
        assert "failure_error_type" not in replacement.state
        self.dispatch.assert_called_once()

    def test_reconnect_before_failure_is_recovered_after_the_failure_commits(self) -> None:
        self._block()
        retry_github_blocked_implementations(self.team.id)
        assert self.task.runs.count() == 1
        with (
            patch(
                "products.signals.backend.implementation_github_recovery_tasks.retry_github_blocked_implementations.delay",
                side_effect=retry_github_blocked_implementations,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._fail()
        assert self.task.runs.count() == 2
        self.dispatch.assert_called_once()

    @parameterized.expand(["revision", "revoked", "expired"])
    def test_replacement_revalidates_the_request_before_execution(self, case: str) -> None:
        self._block()
        self._fail()
        retry_report_implementation(self.team.id, str(self.report.id))
        replacement = self.task.runs.exclude(id=self.task_run.id).get()
        if case == "revision":
            self.report.content_revision_count = (self.report.content_revision_count or 0) + 1
            self.report.save(update_fields=["content_revision_count"])
        elif case == "revoked":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        else:
            replacement.state["github_recovery_deadline"] = (timezone.now() - timedelta(seconds=1)).isoformat()
            replacement.save(update_fields=["state"])
        with pytest.raises(TaskRunPreflightError) as error:
            require_implementation_github_access(str(replacement.id), True)
        assert error.value.reason == ("GitHubRecoveryExpired" if case == "expired" else "GitHubRecoveryIneligible")

    @parameterized.expand(
        [
            "expired",
            "revision",
            "repository",
            "revoked",
            "task_access_revoked",
            "source_privacy",
            "cancelled",
            "ordinary_failure",
            "newer_attempt",
        ]
    )
    def test_reconnect_does_not_retry_ineligible_or_superseded_attempts(self, case: str) -> None:
        self._block()
        self._fail()
        if case == "expired":
            self.task_run.state["github_recovery_deadline"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        elif case == "revision":
            self.report.content_revision_count = (self.report.content_revision_count or 0) + 1
            self.report.save(update_fields=["content_revision_count"])
        elif case == "repository":
            self.task.repository = "example/other"
            self.task.save(update_fields=["repository"])
        elif case == "revoked":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        elif case == "task_access_revoked":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save(update_fields=["available_product_features"])
            OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
                level=OrganizationMembership.Level.MEMBER
            )
            AccessControl.objects.create(team=self.team, resource="task", access_level="viewer")
        elif case == "source_privacy":
            self.source_privacy.return_value = False
        elif case == "cancelled":
            self.task_run.status = TaskRun.Status.CANCELLED
        elif case == "ordinary_failure":
            self.task_run.state["failure_error_type"] = "OtherStartupFailure"
        elif case == "newer_attempt":
            TaskRun.objects.create(
                team=self.team,
                task=self.task,
                status=TaskRun.Status.FAILED,
                environment=TaskRun.Environment.CLOUD,
                created_at=timezone.now() + timedelta(seconds=1),
            )
        self.task_run.save(update_fields=["state", "status"])
        retry_report_implementation(self.team.id, str(self.report.id))
        self.dispatch.assert_not_called()

    @parameterized.expand(["discussion", "local", "running", "other_origin"])
    def test_preflight_leaves_other_task_runs_unchanged(self, case: str) -> None:
        if case == "discussion":
            self.report.report_tasks.all().delete()
        elif case == "local":
            self.task_run.environment = TaskRun.Environment.LOCAL
        elif case == "running":
            self.task_run.status = TaskRun.Status.IN_PROGRESS
        elif case == "other_origin":
            self.task.origin_product = Task.OriginProduct.USER_CREATED
            self.task.save(update_fields=["origin_product"])
        self.task_run.save(update_fields=["environment", "status"])
        require_implementation_github_access(str(self.task_run.id), True)
        self.readiness.assert_not_called()
