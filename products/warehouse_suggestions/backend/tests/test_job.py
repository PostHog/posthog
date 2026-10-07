from datetime import date, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Edge, Node, NodeType
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus
from products.warehouse_suggestions.backend.logic.job import TeamRunStatus, run_team
from products.warehouse_suggestions.backend.models import WarehouseSuggestion, WarehouseSuggestionTeamConfig
from products.warehouse_suggestions.backend.tests.rollup import RollupRead, seed_reads

TODAY = date.today()
SCENES = ("SQLEditor", "Dashboard")


class TestRunTeam(ClickhouseTestMixin, BaseTest):
    def _view(self, name: str, dag: DAG, *, materialized: bool = False) -> tuple[DataWarehouseSavedQuery, Node]:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "SELECT timestamp, event FROM events"},
            is_materialized=materialized,
        )
        node = Node.objects.create(
            team=self.team,
            dag=dag,
            name=name,
            saved_query=saved_query,
            type=NodeType.MAT_VIEW if materialized else NodeType.VIEW,
        )
        return saved_query, node

    def test_proposes_each_kind_from_a_month_of_reads_and_surfaces_them(self) -> None:
        dag = DAG.objects.create(team=self.team, name="Default")
        busy, _ = self._view("busy_orders", dag)
        unread, _ = self._view("old_rollup", dag, materialized=True)
        feeds_another, source_node = self._view("feeds_another", dag, materialized=True)
        _, dependent_node = self._view("reads_feeds_another", dag)
        Edge.objects.create(team=self.team, dag=dag, source=source_node, target=dependent_node)
        seed_reads(
            self.team.pk,
            [
                RollupRead(
                    subject_id=busy.id,
                    day=TODAY - timedelta(days=day),
                    request_id=f"{day}-{request}",
                    user_id=1 + (day + request) % 6,
                    scene=SCENES[request],
                    read_alone=True,
                    duration_ms=30_000,
                )
                for day in range(1, 31)
                for request in range(2)
            ],
        )

        result = run_team(self.team.pk, run_id="run-1", today=TODAY)

        assert result.status == TeamRunStatus.PROCESSED
        assert sorted(
            WarehouseSuggestion.objects.for_team(self.team.pk).values_list("kind", "subject_id", "status")
        ) == sorted(
            [
                (WarehouseSuggestionKind.CERTIFY, busy.id, WarehouseSuggestionStatus.PROPOSED),
                (WarehouseSuggestionKind.MATERIALIZE, busy.id, WarehouseSuggestionStatus.PROPOSED),
                (WarehouseSuggestionKind.DEPRECATE, unread.id, WarehouseSuggestionStatus.PROPOSED),
            ]
        )
        assert not WarehouseSuggestion.objects.for_team(self.team.pk).filter(subject_id=feeds_another.id).exists()
        assert not WarehouseSuggestion.objects.for_team(self.team.pk).filter(surfaced_at__isnull=True).exists()
        materialize = WarehouseSuggestion.objects.for_team(self.team.pk).get(kind=WarehouseSuggestionKind.MATERIALIZE)
        assert (materialize.payload["refresh_interval_seconds"], materialize.run_id) == (24 * 60 * 60, "run-1")

    def test_a_team_without_view_reads_is_recorded_as_not_eligible(self) -> None:
        result = run_team(self.team.pk, run_id="run-1", today=TODAY)

        config = WarehouseSuggestionTeamConfig.objects.get(team_id=self.team.pk)
        assert (result.status, config.eligible, config.last_run_at is not None) == (
            TeamRunStatus.NOT_ELIGIBLE,
            False,
            True,
        )
