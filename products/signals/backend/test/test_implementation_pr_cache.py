import json
from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError

from parameterized import parameterized

from products.signals.backend.implementation_pr import report_ids_for_implementation_pr
from products.signals.backend.implementation_pr_cache import live_implementation_pr_flags
from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
    SignalReportTask,
)
from products.tasks.backend.models import Task, TaskRun

PR_URL = "https://github.com/example/app/pull/7"


class TestImplementationPrCache(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s"
        )

    def _cached_and_live(self) -> tuple[tuple[bool, bool], tuple[bool, bool]]:
        live = live_implementation_pr_flags(self.team.id)
        row = (
            SignalReport.objects.filter(id=self.report.id)
            .annotate(live_has_implementation_pr=live.has_pr, live_has_active_implementation_pr=live.has_active_pr)
            .values(
                "has_implementation_pr",
                "has_active_implementation_pr",
                "live_has_implementation_pr",
                "live_has_active_implementation_pr",
            )[0]
        )
        return (
            (row["has_implementation_pr"], row["has_active_implementation_pr"]),
            (row["live_has_implementation_pr"], row["live_has_active_implementation_pr"]),
        )

    def _task(self, *, with_pr: bool) -> tuple[Task, TaskRun]:
        task = Task.objects.create(team=self.team, title="Implementation", description="", origin_product="signals")
        run = TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.COMPLETED)
        if with_pr:
            # A queryset update, so the run's own receiver is not what links it here.
            TaskRun.objects.filter(id=run.id).update(output={"pr_url": PR_URL})
        return task, run

    def _task_run_artefact(self, task: Task, run: TaskRun) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type=SignalReportArtefact.ArtefactType.TASK_RUN,
            task_id=task.id,
            content=json.dumps(
                {"task_id": str(task.id), "run_id": str(run.id), "product": "signals", "type": "implementation"}
            ),
        )

    def _link_assignment(self) -> None:
        SignalReportAssignment.all_teams.create(
            team=self.team, report=self.report, pr_url=PR_URL, repository="example/app", pr_number=7, pr_state="open"
        )

    def _link_pull_request(self) -> None:
        pull_request = SignalReportPullRequest.objects.create(
            team=self.team, repository="example/app", number=7, url=PR_URL, state="open"
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
            pull_request=pull_request,
            content="{}",
        )

    def _link_task_run_artefact(self) -> None:
        self._task_run_artefact(*self._task(with_pr=True))

    def _link_task_run_output(self) -> None:
        task, run = self._task(with_pr=False)
        self._task_run_artefact(task, run)
        run.output = {"pr_url": PR_URL}
        # The assignment sync on the same save queues tracker linking, which retries without a provider.
        with patch("products.signals.backend.tasks.link_report_tracker_issues.delay"):
            run.save(update_fields=["output"])

    def _link_legacy_report_task(self) -> None:
        task, _ = self._task(with_pr=True)
        SignalReportTask.objects.create(team=self.team, report=self.report, task=task, relationship="implementation")

    def _link_task_assignment(self) -> None:
        task, _ = self._task(with_pr=True)
        SignalReportAssignment.all_teams.create(
            team=self.team, report=self.report, actor_kind=SignalActorKind.TASK, actor_task_id=task.id
        )

    @parameterized.expand(
        [
            ("assignment", "_link_assignment"),
            ("pull_request_artefact", "_link_pull_request"),
            ("task_run_artefact", "_link_task_run_artefact"),
            ("task_run_output_written_after_the_link", "_link_task_run_output"),
            ("legacy_report_task", "_link_legacy_report_task"),
        ]
    )
    def test_each_link_source_keeps_the_cached_flags_equal_to_the_live_filter(self, _name: str, link: str) -> None:
        write: Callable[[], None] = getattr(self, link)
        with self.captureOnCommitCallbacks(execute=True):
            write()

        cached, live = self._cached_and_live()
        assert live == (True, True)
        assert cached == live

    @parameterized.expand(
        [
            ("assignment", "_link_assignment"),
            ("pull_request_artefact", "_link_pull_request"),
            ("task_run_artefact", "_link_task_run_artefact"),
            ("legacy_report_task", "_link_legacy_report_task"),
            ("task_assignment", "_link_task_assignment"),
        ]
    )
    def test_each_link_source_resolves_the_report_for_its_pull_request(self, _name: str, link: str) -> None:
        getattr(self, link)()

        assert report_ids_for_implementation_pr(team_id=self.team.id, repository="Example/App", pr_number=7) == [
            str(self.report.id)
        ]
        assert report_ids_for_implementation_pr(team_id=self.team.id, repository="example/app", pr_number=8) == []

    def test_a_team_without_reports_skips_the_task_run_scan(self) -> None:
        self._task(with_pr=True)
        self.report.delete()

        with self.assertNumQueries(1):
            assert report_ids_for_implementation_pr(team_id=self.team.id, repository="example/app", pr_number=7) == []

    def test_a_merged_pull_request_stops_counting_as_active(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._link_pull_request()
        pull_request = SignalReportPullRequest.objects.get(team=self.team, url=PR_URL)

        with self.captureOnCommitCallbacks(execute=True):
            pull_request.state = "merged"
            pull_request.save()

        cached, live = self._cached_and_live()
        assert live == (True, False)
        assert cached == live

    @parameterized.expand([("output_cleared", "clear_output"), ("task_deleted", "delete_task")])
    def test_removing_the_only_task_pr_clears_the_cached_flags(self, _name: str, removal: str) -> None:
        task, run = self._task(with_pr=True)
        SignalReportTask.objects.create(team=self.team, report=self.report, task=task, relationship="implementation")
        self._task_run_artefact(task, run)
        SignalReport.objects.filter(id=self.report.id).update(
            has_implementation_pr=True, has_active_implementation_pr=True
        )

        with self.captureOnCommitCallbacks(execute=True):
            if removal == "clear_output":
                run.output = None
                run.save(update_fields=["output"])
            else:
                Task.objects.filter(id=task.id).delete()

        cached, live = self._cached_and_live()
        assert live == (False, False)
        assert cached == live

    def test_a_failed_refresh_is_retried_by_a_task(self) -> None:
        with (
            patch(
                "products.signals.backend.implementation_pr_cache.refresh_implementation_pr_cache",
                side_effect=OperationalError("connection reset"),
            ),
            patch("products.signals.backend.tasks.refresh_report_implementation_pr_cache.delay") as retry,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._link_assignment()

        retry.assert_called_once_with(self.team.id, report_ids=[str(self.report.id)], pull_request_ids=[], task_ids=[])
