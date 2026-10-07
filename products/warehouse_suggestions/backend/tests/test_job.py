from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Edge, Node, NodeType
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus
from products.warehouse_suggestions.backend.logic.job import TeamRunStatus, run_team
from products.warehouse_suggestions.backend.logic.reads import RollupDays
from products.warehouse_suggestions.backend.logic.rules import RULES
from products.warehouse_suggestions.backend.models import WarehouseSuggestion, WarehouseSuggestionTeamConfig
from products.warehouse_suggestions.backend.tests.rollup import RollupRead, seed_reads
from products.warehouse_suggestions.backend.tests.test_suggestions import ingest_one, make_draft

TODAY = date.today()
NOW = datetime.combine(TODAY, time(hour=9), tzinfo=UTC)
BEFORE_THE_WINDOW = NOW - timedelta(days=2 * RULES.window_days)
SCENES = ("SQLEditor", "Dashboard")
FULL_ROLLUP = RollupDays(days_with_data=RULES.window_days, recent_days_with_data=RULES.lifecycle.expire_after_days)


class TestRunTeam(ClickhouseTestMixin, BaseTest):
    def _view(
        self, name: str, dag: DAG, *, materialized: bool = False, created_at: datetime = BEFORE_THE_WINDOW
    ) -> tuple[DataWarehouseSavedQuery, Node]:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "SELECT timestamp, event FROM events"},
            is_materialized=materialized,
        )
        DataWarehouseSavedQuery.objects.filter(id=saved_query.id).update(created_at=created_at)
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
        created_today, _ = self._view("new_rollup", dag, materialized=True, created_at=NOW)
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

        result = run_team(self.team.pk, run_id="run-1", today=TODAY, rollup_days=FULL_ROLLUP, now=NOW)

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
        assert not (
            WarehouseSuggestion.objects.for_team(self.team.pk)
            .filter(subject_id__in=[feeds_another.id, created_today.id])
            .exists()
        )
        assert not WarehouseSuggestion.objects.for_team(self.team.pk).filter(surfaced_at__isnull=True).exists()
        materialize = WarehouseSuggestion.objects.for_team(self.team.pk).get(kind=WarehouseSuggestionKind.MATERIALIZE)
        assert (materialize.payload["refresh_interval_seconds"], materialize.run_id) == (24 * 60 * 60, "run-1")

    def test_a_team_without_view_reads_is_recorded_as_not_eligible_and_its_open_suggestions_still_resolve(
        self,
    ) -> None:
        about_a_deleted_view = ingest_one(self.team.pk, make_draft(subject_id=uuid4()))

        result = run_team(self.team.pk, run_id="run-1", today=TODAY, rollup_days=FULL_ROLLUP, now=NOW)

        config = WarehouseSuggestionTeamConfig.objects.get(team_id=self.team.pk)
        about_a_deleted_view.refresh_from_db()
        assert (result.status, config.eligible, config.last_run_at is not None, about_a_deleted_view.status) == (
            TeamRunStatus.NOT_ELIGIBLE,
            False,
            True,
            WarehouseSuggestionStatus.AUTO_RESOLVED,
        )
