import uuid
import dataclasses
from collections.abc import Mapping
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.models.team import Team

from products.warehouse_suggestions.backend.facade.contracts import CertifyPayload
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus
from products.warehouse_suggestions.backend.logic.candidates.base import MeasurementRequest
from products.warehouse_suggestions.backend.logic.candidates.registry import CANDIDATES
from products.warehouse_suggestions.backend.logic.job import TeamRunResult, TeamRunStatus
from products.warehouse_suggestions.backend.logic.reads import RollupDays
from products.warehouse_suggestions.backend.logic.rules import RULES
from products.warehouse_suggestions.backend.logic.suggestions import upsert_suggestions
from products.warehouse_suggestions.backend.logic.view_costs import MeasurementOutcome
from products.warehouse_suggestions.backend.models import WarehouseSuggestion
from products.warehouse_suggestions.backend.temporal import (
    ACTIVITIES as WAREHOUSE_SUGGESTIONS_ACTIVITIES,
    WORKFLOWS,
)
from products.warehouse_suggestions.backend.temporal.activities import run_batch, team_batches
from products.warehouse_suggestions.backend.temporal.contracts import (
    WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME,
    BatchOutcome,
    WarehouseSuggestionsInputs,
)
from products.warehouse_suggestions.backend.tests.factories import context, team_reads, view_subject

ACTIVITIES = "products.warehouse_suggestions.backend.temporal.activities"
READS = "products.warehouse_suggestions.backend.logic.reads"
TIMEOUT_EXCEEDED = 159
WORKFLOWS_MODULE = "products.warehouse_suggestions.backend.temporal.workflows"


class TestTeamBatches(BaseTest):
    @parameterized.expand(
        [
            ("kill_switch_off", KillSwitchLevel.OFF, True),
            ("kill_switch_on", KillSwitchLevel.LIGHT, False),
        ]
    )
    def test_picks_main_environments_without_the_flag_skips_demo_teams_and_stops_under_the_kill_switch(
        self, _name: str, kill_switch: KillSwitchLevel, expect_team: bool
    ) -> None:
        demo_team = Team.objects.create(organization=self.organization, is_demo=True)
        unflagged_team = Team.objects.create(organization=self.organization)
        child_environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team
        )

        with (
            patch(f"{ACTIVITIES}.get_kill_switch_level", return_value=kill_switch),
            patch("posthoganalytics.feature_enabled", return_value=False),
        ):
            batches = team_batches(
                WarehouseSuggestionsInputs(
                    team_ids=[self.team.pk, demo_team.pk, unflagged_team.pk, child_environment.pk]
                )
            )

        assert batches == ([[self.team.pk, unflagged_team.pk]] if expect_team else [])

    def test_picks_an_idle_team_that_still_has_an_accepted_suggestion(self) -> None:
        dismissed_team = Team.objects.create(organization=self.organization)
        for team, status in (
            (self.team, WarehouseSuggestionStatus.ACCEPTED),
            (dismissed_team, WarehouseSuggestionStatus.DISMISSED),
        ):
            draft = CANDIDATES[WarehouseSuggestionKind.CERTIFY].draft(
                context(team_reads({}), team_id=team.pk),
                view_subject(uuid.uuid4()),
                CertifyPayload(subject_name="orders"),
                score=1,
                score_inputs={},
            )
            upsert_suggestions(team.pk, [draft])
            WarehouseSuggestion.objects.for_team(team.pk).update(status=status)

        with (
            patch(f"{ACTIVITIES}.get_kill_switch_level", return_value=KillSwitchLevel.OFF),
            patch(f"{ACTIVITIES}._teams_with_reads", return_value=[]),
        ):
            batches = team_batches(WarehouseSuggestionsInputs())

        assert batches == [[self.team.pk]]


class FakeClickHouse:
    def __init__(self, *, shared_read_fails: bool = False) -> None:
        self.shared_reads: set[tuple[int, ...]] = set()
        self.own_reads: set[int] = set()
        self._shared_read_fails = shared_read_fails

    def __call__(
        self, sql: str, params: Mapping[str, Any], *, settings: Mapping[str, Any], team_id: int | None = None
    ) -> list[tuple[Any, ...]]:
        if "team_ids" not in params:
            return [(RULES.window_days, RULES.lifecycle.expire_after_days)]
        if team_id is not None:
            self.own_reads.add(team_id)
            return []
        self.shared_reads.add(params["team_ids"])
        if self._shared_read_fails:
            raise ServerException("Timeout exceeded", code=TIMEOUT_EXCEEDED)
        return []


class TestRunBatch(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team_ids = [self.team.pk, *(Team.objects.create(organization=self.organization).pk for _ in range(2))]

    def _run_batch(self, clickhouse: FakeClickHouse) -> BatchOutcome:
        with patch(f"{READS}.sync_execute", clickhouse):
            return run_batch(self.team_ids, run_id="run-1")

    def test_reads_each_team_alone_when_the_shared_read_fails(self) -> None:
        clickhouse = FakeClickHouse(shared_read_fails=True)

        outcome = self._run_batch(clickhouse)

        assert (outcome.not_eligible, outcome.failed, clickhouse.own_reads) == (3, 0, set(self.team_ids))

    def test_reads_a_team_with_its_own_clickhouse_settings_alone(self) -> None:
        *shared_team_ids, own_settings_team_id = self.team_ids
        clickhouse = FakeClickHouse()

        with override_settings(CLICKHOUSE_PER_TEAM_QUERY_SETTINGS={str(own_settings_team_id): {"max_threads": 1}}):
            outcome = self._run_batch(clickhouse)

        assert (clickhouse.shared_reads, clickhouse.own_reads, outcome.not_eligible) == (
            {tuple(shared_team_ids)},
            {own_settings_team_id},
            3,
        )


async def test_a_worker_measures_the_most_recomputed_views_across_teams_first() -> None:
    task_queue = str(uuid.uuid4())
    rarely_recomputed_view = uuid.uuid4()
    often_recomputed_view = uuid.uuid4()
    measurement_requests = {
        1: (MeasurementRequest(subject=view_subject(rarely_recomputed_view), consumer_runs_per_month=10),),
        2: (MeasurementRequest(subject=view_subject(often_recomputed_view), consumer_runs_per_month=100),),
        3: (),
    }
    one_measurement_per_run = dataclasses.replace(
        RULES, measurement=dataclasses.replace(RULES.measurement, max_per_run=1)
    )
    with (
        patch(f"{ACTIVITIES}.team_batches", return_value=[[1, 2, 3]]),
        patch(f"{ACTIVITIES}.RULES", one_measurement_per_run),
        patch(f"{WORKFLOWS_MODULE}.RULES", one_measurement_per_run),
        patch(f"{ACTIVITIES}.read_rollup_days", return_value=RollupDays(days_with_data=30, recent_days_with_data=7)),
        patch(
            f"{ACTIVITIES}.read_teams_reads",
            side_effect=lambda team_ids, *_: {team_id: team_reads({}) for team_id in team_ids},
        ),
        patch(
            f"{ACTIVITIES}.run_team",
            side_effect=lambda team_id, **_: TeamRunResult(
                team_id=team_id,
                status=TeamRunStatus.PROCESSED,
                measurement_requests=measurement_requests[team_id],
            ),
        ),
        patch(f"{ACTIVITIES}.measure_view_cost", return_value=MeasurementOutcome.MEASURED) as measure_view_cost,
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

    assert outcome.processed == 3
    measure_view_cost.assert_called_once_with(2, often_recomputed_view, one_measurement_per_run.measurement)
