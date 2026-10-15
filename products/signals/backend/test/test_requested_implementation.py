from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.auto_start import (
    NO_STEERING,
    RequestedImplementation,
    RequestedImplementationUnavailable,
    start_requested_implementation,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_generation.research import ActionabilityAssessment, ActionabilityChoice
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Task, TaskRun


class TestRequestedImplementation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout failure",
            summary="Fix the updated checkout path",
            signal_count=1,
            run_count=2,
            implemented_at_run_count=1,
        )
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            signal_report=self.report,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            title="Implementation: Checkout failure",
            repository="example/repo",
            internal=True,
        )
        self.old_run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status=TaskRun.Status.COMPLETED,
            environment=TaskRun.Environment.CLOUD,
            state={"ai_stage": "implementation", "self_driving_head_branch": "posthog-self-driving/checkout"},
        )
        with transaction.atomic():
            record_implementation_task(
                team_id=self.team.id,
                report_id=str(self.report.id),
                task_id=str(self.task.id),
                run_id=str(self.old_run.id),
                automation_branch="posthog-self-driving/checkout",
            )
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=ActionabilityAssessment(
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
                explanation="There is a specific fix.",
            ),
            attribution=ArtefactAttribution.system(),
        )
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=RepoSelectionResult(repository="example/repo", reason="selected"),
            attribution=ArtefactAttribution.system(),
        )

    def request(self) -> RequestedImplementation:
        return RequestedImplementation(
            team_id=self.team.id,
            report_id=str(self.report.id),
            user_id=self.user.id,
            task_id=str(self.task.id),
            after_run_count=1,
        )

    def test_resumes_existing_task_once_with_fresh_research(self) -> None:
        def fake_run_task(*args: object, **kwargs: object) -> SimpleNamespace:
            new_run = TaskRun.objects.create(
                team=self.team,
                task=self.task,
                status=TaskRun.Status.NOT_STARTED,
                environment=TaskRun.Environment.CLOUD,
                state={"ai_stage": "implementation", "self_driving_head_branch": "posthog-self-driving/checkout"},
            )
            return SimpleNamespace(task=SimpleNamespace(latest_run_id=new_run.id), error=None, run_error=None)

        with (
            patch("products.signals.backend.auto_start.task_run_usage_limited", return_value=False),
            patch.object(tasks_facade, "enforce_self_driving_pr_quota"),
            patch(
                "products.signals.backend.auto_start.self_driving_free_trial_enabled", return_value=False
            ) as free_trial_flag,
            patch.object(tasks_facade, "run_task", side_effect=fake_run_task) as run_task,
        ):
            new_run_id = start_requested_implementation(self.request())
            assert start_requested_implementation(self.request()) == "already_started"

        self.report.refresh_from_db()
        assert self.report.implemented_at_run_count == 2
        assert run_task.call_count == 1
        assert run_task.call_args.kwargs["pipeline_rerun"] is True
        assert run_task.call_args.kwargs["free_trial_enabled"] is False
        free_trial_flag.assert_called_once()
        assert "Fix the updated checkout path" in run_task.call_args.kwargs["validated_data"]["pending_user_message"]
        assert SignalReportArtefact.objects.filter(
            team_id=self.team.id, report_id=self.report.id, type="task_run", content__contains=new_run_id
        ).exists()

    def test_unactionable_research_never_starts_implementation(self) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=ActionabilityAssessment(
                actionability=ActionabilityChoice.NOT_ACTIONABLE,
                already_addressed=False,
                explanation="The evidence does not support a fix.",
            ),
            attribution=ArtefactAttribution.system(),
        )
        with (
            patch("products.signals.backend.auto_start.task_run_usage_limited", return_value=False),
            patch.object(tasks_facade, "enforce_self_driving_pr_quota"),
            patch.object(tasks_facade, "run_task") as run_task,
        ):
            try:
                start_requested_implementation(self.request())
            except RequestedImplementationUnavailable as error:
                assert "not actionable" in str(error)
            else:
                raise AssertionError("Unactionable research started implementation")
        run_task.assert_not_called()

    def test_report_without_prior_implementation_creates_a_linked_task(self) -> None:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="New issue",
            summary="Fix the new issue",
            signal_count=1,
            run_count=1,
        )
        for content in (
            ActionabilityAssessment(
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
                explanation="A code fix is needed.",
            ),
            RepoSelectionResult(repository="example/repo", reason="selected"),
        ):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                content=content,
                attribution=ArtefactAttribution.system(),
            )

        def fake_create_and_run_task(**kwargs: object) -> SimpleNamespace:
            task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                signal_report=report,
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                title=str(kwargs["title"]),
                repository="example/repo",
                internal=True,
            )
            run = TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.NOT_STARTED)
            return SimpleNamespace(task_id=task.id, latest_run=SimpleNamespace(id=run.id))

        with (
            patch("products.signals.backend.auto_start.task_run_usage_limited", return_value=False),
            patch.object(tasks_facade, "enforce_self_driving_pr_quota"),
            patch.object(tasks_facade, "create_and_run_task", side_effect=fake_create_and_run_task),
            patch("products.signals.backend.auto_start.resolve_agent_runtime", return_value=AgentRuntime()),
            patch("products.signals.backend.auto_start.load_report_steering", return_value=NO_STEERING),
            patch("products.signals.backend.auto_start._fetch_source_references", return_value=[]),
            patch("products.signals.backend.auto_start.self_driving_free_trial_enabled", return_value=False),
            patch("products.signals.backend.auto_start.create_tracker_issue_for_report"),
            patch("products.signals.backend.auto_start._capture_steering_attached"),
        ):
            assert (
                start_requested_implementation(
                    RequestedImplementation(
                        team_id=self.team.id,
                        report_id=str(report.id),
                        user_id=self.user.id,
                        task_id=None,
                        after_run_count=0,
                    )
                )
                == "created"
            )

        report.refresh_from_db()
        assert report.implemented_at_run_count == 1
        assert SignalReportTask.objects.filter(
            team_id=self.team.id, report_id=report.id, relationship="implementation"
        ).exists()

    def test_repository_change_creates_a_new_task_for_the_new_research(self) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=RepoSelectionResult(repository="example/other", reason="new evidence"),
            attribution=ArtefactAttribution.system(),
        )

        def fake_create_and_run_task(**kwargs: object) -> SimpleNamespace:
            task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                signal_report=self.report,
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                title=str(kwargs["title"]),
                repository="example/other",
                internal=True,
            )
            run = TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.NOT_STARTED)
            return SimpleNamespace(task_id=task.id, latest_run=SimpleNamespace(id=run.id))

        with (
            patch("products.signals.backend.auto_start.task_run_usage_limited", return_value=False),
            patch.object(tasks_facade, "enforce_self_driving_pr_quota"),
            patch.object(tasks_facade, "create_and_run_task", side_effect=fake_create_and_run_task),
            patch("products.signals.backend.auto_start.resolve_agent_runtime", return_value=AgentRuntime()),
            patch("products.signals.backend.auto_start.load_report_steering", return_value=NO_STEERING),
            patch("products.signals.backend.auto_start._fetch_source_references", return_value=[]),
            patch("products.signals.backend.auto_start.self_driving_free_trial_enabled", return_value=False),
            patch("products.signals.backend.auto_start.create_tracker_issue_for_report"),
            patch("products.signals.backend.auto_start._capture_steering_attached"),
        ):
            assert start_requested_implementation(self.request()) == "created"

        self.report.refresh_from_db()
        assert self.report.implemented_at_run_count == 2
        assert (
            SignalReportTask.objects.filter(
                team_id=self.team.id, report_id=self.report.id, relationship="implementation"
            ).count()
            == 2
        )
        assert Task.objects.filter(team=self.team, signal_report=self.report, repository="example/other").exists()
