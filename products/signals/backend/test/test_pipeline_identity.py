from posthog.test.base import BaseTest

from django.apps import apps

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.pipeline_identity import (
    AI_STAGE_IMPLEMENTATION,
    AI_STAGE_RESEARCH,
    pipeline_writer_identity,
)
from products.signals.backend.scout_harness.note_targets import (
    PIPELINE_AUDIENCE_IMPLEMENTATION,
    PIPELINE_AUDIENCE_REPORT_RESEARCH,
)


def _create_task_run(team, *, origin_product: str, ai_stage: str | None):
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    task = Task.objects.create(
        team=team,
        title="pipeline run",
        description="pipeline run",
        origin_product=origin_product,
    )
    state = {"ai_stage": ai_stage} if ai_stage else {}
    return TaskRun.objects.create(task=task, team=team, state=state)


class TestPipelineWriterIdentity(BaseTest):
    @parameterized.expand(
        [
            ("research", AI_STAGE_RESEARCH, PIPELINE_AUDIENCE_REPORT_RESEARCH),
            ("implementation", AI_STAGE_IMPLEMENTATION, PIPELINE_AUDIENCE_IMPLEMENTATION),
        ]
    )
    def test_resolves_the_stage_that_started_the_run(self, _name: str, ai_stage: str, expected: str) -> None:
        Task = apps.get_model("tasks", "Task")
        run = _create_task_run(self.team, origin_product=Task.OriginProduct.SIGNAL_REPORT, ai_stage=ai_stage)

        assert pipeline_writer_identity(task_id=run.task_id, team_id=self.team.id) == expected

    @parameterized.expand(
        [
            # A scout run carries a `scout:*` stage under its own origin; it must never resolve to
            # a pipeline identity, or a scout's memory would be filed under a stage that didn't
            # write it — and its `created_by_run` attribution would be contradicted.
            ("scout_origin", "signals_scout", "scout:signals-scout-apm"),
            # An origin the pipeline doesn't own can't buy a pipeline identity by naming a stage.
            ("foreign_origin_naming_a_stage", "user_created", AI_STAGE_RESEARCH),
            # A repo-selection run is pipeline-owned but writes no memory, so it stays unmapped.
            ("unmapped_stage", "signal_report", "repo_selection"),
            ("no_stage", "signal_report", None),
        ]
    )
    def test_returns_none_for_everything_else(self, _name: str, origin_product: str, ai_stage: str | None) -> None:
        run = _create_task_run(self.team, origin_product=origin_product, ai_stage=ai_stage)

        assert pipeline_writer_identity(task_id=run.task_id, team_id=self.team.id) is None

    def test_is_scoped_to_the_team(self) -> None:
        # The task id reaches this from a token bound to one team. A run on another team must not
        # lend its stage to this team's write.
        other = Team.objects.create(organization=self.organization, name="other-team")
        Task = apps.get_model("tasks", "Task")
        run = _create_task_run(other, origin_product=Task.OriginProduct.SIGNAL_REPORT, ai_stage=AI_STAGE_RESEARCH)

        assert pipeline_writer_identity(task_id=run.task_id, team_id=self.team.id) is None

    def test_no_bound_task_resolves_to_no_identity(self) -> None:
        assert pipeline_writer_identity(task_id=None, team_id=self.team.id) is None
