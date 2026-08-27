from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.test.base import BaseTest

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.artefact_schemas import (
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_RESEARCH,
    SignalFinding,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_generation.open_prs import collect_open_self_driving_prs

if TYPE_CHECKING:
    from products.tasks.backend.models import Task as TaskModel


# `products.tasks` is an isolated product, so its models are reached through the app registry.
def _task_model() -> type["TaskModel"]:
    return apps.get_model("tasks", "Task")


class TestCollectOpenSelfDrivingPrs(BaseTest):
    def _report(self, *, title: str = "fix(replay): stop dropping events") -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title=title, signal_count=1, total_weight=1.0
        )

    def _pr_run(
        self,
        report: SignalReport,
        *,
        output: dict,
        branch: str = "posthog/fix-replay",
        relationship: str = TASK_RUN_TYPE_IMPLEMENTATION,
    ) -> None:
        Task, TaskRun = _task_model(), apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        SignalReportTask.objects.create(team=self.team, report=report, task=task, relationship=relationship)
        TaskRun.objects.create(
            team=self.team,
            task=task,
            branch=branch,
            output=output,
            created_at=timezone.now() - timedelta(days=1),
        )

    def _finding(self, report: SignalReport, *, code_paths: list[str]) -> None:
        SignalReportArtefact.append(
            team_id=self.team.id,
            report_id=str(report.id),
            content=SignalFinding(
                signal_id="sig-1",
                relevant_code_paths=code_paths,
                data_queried="Queried the replay ingestion events.",
                verified=True,
            ),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )

    def test_collects_the_sibling_report_pr_and_skips_the_report_being_researched(self):
        researched = self._report(title="fix(replay): drop rate climbing")
        sibling = self._report()
        self._pr_run(researched, output={"pr_url": "https://github.com/PostHog/posthog/pull/1"})
        self._pr_run(sibling, output={"pr_url": "https://github.com/PostHog/posthog/pull/2"})
        self._finding(sibling, code_paths=["products/replay/backend/ingest.py"])

        collected = collect_open_self_driving_prs(
            team_id=self.team.id, repository="PostHog/posthog", exclude_report_id=str(researched.id)
        )

        assert [pr.pr_url for pr in collected] == ["https://github.com/PostHog/posthog/pull/2"]
        assert collected[0].report_id == str(sibling.id)
        assert collected[0].report_title == "fix(replay): stop dropping events"
        assert collected[0].repository == "PostHog/posthog"
        assert collected[0].branch == "posthog/fix-replay"
        assert collected[0].code_paths == ("products/replay/backend/ingest.py",)

    @parameterized.expand(
        [
            ("merged_state", {"pr_url": "https://github.com/PostHog/posthog/pull/2", "pr_state": "merged"}),
            ("closed_state", {"pr_url": "https://github.com/PostHog/posthog/pull/2", "pr_state": "closed"}),
            ("merged_flag", {"pr_url": "https://github.com/PostHog/posthog/pull/2", "pr_merged": True}),
            ("no_pr_at_all", {}),
        ]
    )
    def test_omits_work_that_is_not_in_flight(self, _name, output):
        self._pr_run(self._report(), output=output)

        assert collect_open_self_driving_prs(team_id=self.team.id, repository="PostHog/posthog") == []

    # A research run reads other people's PRs while checking what is already in flight, and can
    # record one on its output. Surfacing that back as "PostHog already opened this" would tell the
    # next report a stranger's PR is ours.
    def test_ignores_a_pr_url_a_research_run_only_looked_at(self):
        self._pr_run(
            self._report(),
            output={"pr_url": "https://github.com/PostHog/posthog/pull/2"},
            relationship=TASK_RUN_TYPE_RESEARCH,
        )

        assert collect_open_self_driving_prs(team_id=self.team.id, repository="PostHog/posthog") == []

    # The block is capped for the prompt budget, so when it has to drop entries it must keep the
    # ones that can actually collide: PRs in the repository this run is about.
    def test_ranks_the_researched_repository_ahead_of_others(self):
        other_repo = self._report(title="fix(js): swallow init error")
        same_repo = self._report()
        self._pr_run(other_repo, output={"pr_url": "https://github.com/PostHog/posthog-js/pull/9"})
        self._pr_run(same_repo, output={"pr_url": "https://github.com/PostHog/posthog/pull/2"})

        collected = collect_open_self_driving_prs(team_id=self.team.id, repository="PostHog/posthog", limit=1)

        assert [pr.repository for pr in collected] == ["PostHog/posthog"]
