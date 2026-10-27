from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.facade.api import (
    WorkflowScoutRunStarted,
    run_scout_for_source,
    scout_reports_for_source,
    scout_run_ids_for_source,
    scout_source_for_run,
    task_has_source_report,
)
from products.signals.backend.models import SignalReport, SignalReportTask, SignalScoutConfig, SignalScoutRun


class TestSourceScoutOwnership(BaseTest):
    @parameterized.expand(
        [("owned", "bets", None), ("wrong_source", "other-product", None), ("paused", "bets", "The bet is paused.")]
    )
    def test_source_trigger_respects_ownership_and_the_registered_guard(
        self, name: str, source: str, refusal: str | None
    ) -> None:
        config = SignalScoutConfig.objects.for_team(self.team.id).create(
            team=self.team, skill_name="bet-scout", source_product="bets", source_id="bet-1"
        )
        result = WorkflowScoutRunStarted(skill_name=config.skill_name, workflow_id="native-workflow")
        with (
            patch("products.signals.backend.facade.api.scout_source_refusal", return_value=refusal),
            patch("products.signals.backend.facade.api.start_workflow_scout_run", return_value=result) as start,
        ):
            if source != "bets" or refusal:
                with self.assertRaises(ValueError):
                    run_scout_for_source(self.team.id, source, str(config.id))
                assert not start.called
            else:
                assert run_scout_for_source(self.team.id, source, str(config.id)).workflow_id == "native-workflow"

    @parameterized.expand(
        [
            ("snapshot", False, {"source_product": "bets", "source_id": "bet-1"}),
            ("deleted_config", True, {"source_product": "bets", "source_id": "bet-1"}),
            ("retagged_config", False, {"source_product": "bets", "source_id": "bet-1"}),
            ("legacy", False, {}),
            ("legacy_null", False, None),
        ]
    )
    def test_source_keeps_its_own_reports_and_spending_runs(
        self, config_state: str, delete_config: bool, metadata: dict[str, str] | None
    ) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(team=self.team, title="Source scout", description="Find opportunities")
        task_run = TaskRun.objects.create(team=self.team, task=task)
        config = SignalScoutConfig.objects.for_team(self.team.id).create(
            team=self.team, skill_name="bet-scout", source_product="bets", source_id="bet-1"
        )
        authored = SignalReport.objects.create(team=self.team, title="Authored finding")
        edited = SignalReport.objects.create(team=self.team, title="Another scout's finding")
        SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=task_run,
            scout_config=config,
            skill_name=config.skill_name,
            skill_version=1,
            metadata=metadata,
            emitted_report_ids=[str(authored.id)],
            edited_report_ids=[str(edited.id)],
        )
        SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=TaskRun.objects.create(team=self.team, task=task),
            skill_name=config.skill_name,
            skill_version=1,
            emitted_report_ids=[str(edited.id)],
        )
        SignalReportTask.objects.create(team=self.team, report=authored, task=task, relationship="implementation")
        other_team = Team.objects.create(organization=self.organization, name="Another project")
        other_task = Task.objects.create(team=other_team, title="Other scout", description="Other project")
        other_run = TaskRun.objects.create(team=other_team, task=other_task)
        SignalScoutRun.objects.for_team(other_team.id).create(
            team=other_team,
            task_run=other_run,
            skill_name=config.skill_name,
            skill_version=1,
            metadata={"source_product": "bets", "source_id": "bet-1"},
            emitted_report_ids=[str(authored.id)],
        )
        if delete_config:
            config.delete()
        elif config_state == "retagged_config":
            config.source_id = "bet-2"
            config.save(update_fields=["source_id"])

        assert [r.report_id for r in scout_reports_for_source(self.team.id, "bets", "bet-1")] == [str(authored.id)]
        assert scout_reports_for_source(self.team.id, "bets", "bet-1", report_id=str(edited.id)) == []
        assert scout_reports_for_source(self.team.id, "bets", "bet-2") == []
        assert scout_run_ids_for_source(self.team.id, "bets", ["bet-1"]) == [task_run.id]
        assert scout_run_ids_for_source(self.team.id, "bets", []) == []
        assert scout_source_for_run(self.team.id, task_run.id, "bets") == "bet-1"
        assert scout_source_for_run(self.team.id, other_run.id, "bets") is None
        assert task_has_source_report(self.team.id, task.id, "bets")
        assert not task_has_source_report(self.team.id, task.id, "another-product")
