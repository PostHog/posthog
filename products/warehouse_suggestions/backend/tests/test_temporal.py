import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.models.team import Team

from products.warehouse_suggestions.backend.logic.job import TeamRunResult, TeamRunStatus
from products.warehouse_suggestions.backend.logic.reads import RollupDays
from products.warehouse_suggestions.backend.temporal import (
    ACTIVITIES as WAREHOUSE_SUGGESTIONS_ACTIVITIES,
    WORKFLOWS,
)
from products.warehouse_suggestions.backend.temporal.activities import team_batches
from products.warehouse_suggestions.backend.temporal.contracts import (
    WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME,
    BatchOutcome,
    WarehouseSuggestionsInputs,
)

ACTIVITIES = "products.warehouse_suggestions.backend.temporal.activities"


class TestTeamBatches(BaseTest):
    @parameterized.expand(
        [
            ("kill_switch_off", KillSwitchLevel.OFF, True),
            ("kill_switch_on", KillSwitchLevel.LIGHT, False),
        ]
    )
    def test_picks_flagged_main_environments_skips_demo_teams_and_stops_under_the_kill_switch(
        self, _name: str, kill_switch: KillSwitchLevel, expect_team: bool
    ) -> None:
        demo_team = Team.objects.create(organization=self.organization, is_demo=True)
        unflagged_team = Team.objects.create(organization=self.organization)
        child_environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team
        )
        flagged = {self.team.pk, demo_team.pk, child_environment.pk}

        with (
            patch(f"{ACTIVITIES}.get_kill_switch_level", return_value=kill_switch),
            patch(f"{ACTIVITIES}.is_warehouse_suggestions_enabled", side_effect=lambda team: team.pk in flagged),
        ):
            batches = team_batches(
                WarehouseSuggestionsInputs(
                    team_ids=[self.team.pk, demo_team.pk, unflagged_team.pk, child_environment.pk]
                )
            )

        assert batches == ([[self.team.pk]] if expect_team else [])


async def test_a_worker_runs_a_nonempty_batch_without_failing_a_team() -> None:
    task_queue = str(uuid.uuid4())
    with (
        patch(f"{ACTIVITIES}.team_batches", return_value=[[1, 2]]),
        patch(f"{ACTIVITIES}.read_rollup_days", return_value=RollupDays(days_with_data=30, recent_days_with_data=7)),
        patch(
            f"{ACTIVITIES}.run_team",
            side_effect=lambda team_id, **_: TeamRunResult(team_id=team_id, status=TeamRunStatus.PROCESSED),
        ),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=WORKFLOWS,
                activities=WAREHOUSE_SUGGESTIONS_ACTIVITIES,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                outcome = await environment.client.execute_workflow(
                    WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME,
                    WarehouseSuggestionsInputs(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    result_type=BatchOutcome,
                )

    assert outcome == BatchOutcome(processed=2)
