from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.test.base import BaseTest

from django.apps import apps
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_RESEARCH,
    SignalFinding,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_generation.open_prs import collect_open_self_driving_prs
from products.signals.backend.task_run_artefacts import append_task_run_artefact
from products.signals.backend.temporal.agentic.report import _load_open_self_driving_prs

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
        associate_via: str = "gate_row",
    ) -> None:
        Task, TaskRun = _task_model(), apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, title="impl", description="d", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        # The two association sources `associated_task_runs` unifies. New associations land as
        # `task_run` artefacts; the gate rows are the legacy half still being migrated out.
        if associate_via == "artefact":
            append_task_run_artefact(
                team_id=self.team.id,
                report_id=str(report.id),
                product=SIGNALS_PRODUCT,
                type=relationship,
                task_id=str(task.id),
            )
        else:
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

    # Both association sources must resolve. New reports link through the `task_run` artefact, so a
    # break there hides exactly the recent PRs this block exists to surface.
    @parameterized.expand([("gate_row",), ("artefact",)])
    def test_collects_the_sibling_report_pr_and_skips_the_report_being_researched(self, associate_via):
        researched = self._report(title="fix(replay): drop rate climbing")
        sibling = self._report()
        self._pr_run(
            researched, output={"pr_url": "https://github.com/PostHog/posthog/pull/1"}, associate_via=associate_via
        )
        self._pr_run(
            sibling, output={"pr_url": "https://github.com/PostHog/posthog/pull/2"}, associate_via=associate_via
        )
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
    # next report a stranger's PR is ours, and wrongly suppress a PR we should have opened.
    @parameterized.expand([("gate_row",), ("artefact",)])
    def test_ignores_a_pr_url_a_research_run_only_looked_at(self, associate_via):
        self._pr_run(
            self._report(),
            output={"pr_url": "https://github.com/PostHog/posthog/pull/2"},
            relationship=TASK_RUN_TYPE_RESEARCH,
            associate_via=associate_via,
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

    # The note is the only record of what research was given, so a wrong `already_addressed: false`
    # stays auditable. Losing it makes the verdict unfalsifiable again.
    def test_activity_records_a_note_naming_the_prs_research_was_shown(self):
        researched = self._report(title="fix(replay): drop rate climbing")
        sibling = self._report()
        self._pr_run(sibling, output={"pr_url": "https://github.com/PostHog/posthog/pull/2"})

        open_prs = _load_open_self_driving_prs(self.team.id, str(researched.id), "PostHog/posthog")

        assert [pr.pr_url for pr in open_prs] == ["https://github.com/PostHog/posthog/pull/2"]
        notes = SignalReportArtefact.objects.filter(
            report_id=researched.id, type=SignalReportArtefact.ArtefactType.NOTE
        )
        assert len(notes) == 1
        assert "https://github.com/PostHog/posthog/pull/2" in notes[0].content
        assert str(sibling.id) in notes[0].content

    def test_activity_writes_no_note_when_nothing_is_in_flight(self):
        researched = self._report()

        assert _load_open_self_driving_prs(self.team.id, str(researched.id), "PostHog/posthog") == []
        assert not SignalReportArtefact.objects.filter(
            report_id=researched.id, type=SignalReportArtefact.ArtefactType.NOTE
        ).exists()
