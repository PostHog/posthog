import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.schema import HogQLQuery

from posthog.models import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
    TrinoCompiledQuery,
    TrinoExpansionMode,
)
from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)
from products.managed_warehouse.backend.temporal.view_translation_workflow import (
    compile_managed_warehouse_team_views_activity,
    finalize_managed_warehouse_view_translation_activity,
    prepare_managed_warehouse_view_translation_activity,
    source_query_hash,
)
from products.managed_warehouse.backend.view_translation import start_managed_warehouse_view_translation


def _membership(team: Team, *, enabled: bool) -> ManagedWarehouseTeamMembership:
    return ManagedWarehouseTeamMembership(
        team_id=team.id,
        organization_id=str(team.organization_id),
        schema_name=f"team_{team.id}",
        enabled=enabled,
        backfill_enabled=True,
        table_names=ManagedWarehouseTableNames(
            events_table=f"events_{team.id}",
            persons_table=f"persons_{team.id}",
            data_imports_schema=f"imports_{team.id}",
        ),
        earliest_event_date=None,
    )


class TestManagedWarehouseViewTranslationActivities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        DuckgresServer.objects.create(
            organization=self.organization,
            host="managed.example.com",
            database="ducklake",
            username="root",
            password="secret",
        )
        self.activity_environment = ActivityEnvironment()

    def test_prepare_snapshots_active_views_for_enabled_warehouse_teams(self) -> None:
        second_team = Team.objects.create(organization=self.organization)
        disabled_team = Team.objects.create(organization=self.organization)
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="active_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=second_team,
            name="active_materialized_view",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            is_materialized=True,
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="endpoint",
            query={"kind": "HogQLQuery", "query": "SELECT 3"},
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="deleted_view",
            query={"kind": "HogQLQuery", "query": "SELECT 4"},
            deleted=True,
        )
        DataWarehouseSavedQuery.objects.create(
            team=disabled_team,
            name="disabled_team_view",
            query={"kind": "HogQLQuery", "query": "SELECT 5"},
        )
        job = ManagedWarehouseViewTranslationJob.objects.create(organization=self.organization)

        memberships = [
            _membership(self.team, enabled=True),
            _membership(second_team, enabled=True),
            _membership(disabled_team, enabled=False),
        ]
        with (
            patch(
                "products.managed_warehouse.backend.temporal.view_translation_workflow.get_ready_trino_catalog_name",
                return_value="managed_catalog",
            ),
            patch(
                "products.managed_warehouse.backend.temporal.view_translation_workflow.list_org_team_memberships",
                return_value=memberships,
            ),
        ):
            preparation = self.activity_environment.run(
                prepare_managed_warehouse_view_translation_activity,
                str(job.id),
            )

        job.refresh_from_db()
        results = ManagedWarehouseViewTranslationResult.all_teams.filter(job=job).order_by("saved_query_name")
        assert preparation.team_ids == (self.team.id, second_team.id)
        assert [(result.saved_query_name, result.is_materialized) for result in results] == [
            ("active_materialized_view", True),
            ("active_view", False),
        ]
        assert job.status == ManagedWarehouseViewTranslationJob.Status.RUNNING
        assert job.total_count == 2

    def test_prepare_snapshots_only_selected_views(self) -> None:
        second_team = Team.objects.create(organization=self.organization)
        unselected = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="unselected_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
        )
        selected = DataWarehouseSavedQuery.objects.create(
            team=second_team,
            name="selected_view",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
        )
        job = ManagedWarehouseViewTranslationJob.objects.create(
            organization=self.organization,
            scope=ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS,
            selected_saved_query_ids=[str(selected.id)],
        )

        with (
            patch(
                "products.managed_warehouse.backend.temporal.view_translation_workflow.get_ready_trino_catalog_name",
                return_value="managed_catalog",
            ),
            patch(
                "products.managed_warehouse.backend.temporal.view_translation_workflow.list_org_team_memberships",
                return_value=[_membership(self.team, enabled=True), _membership(second_team, enabled=True)],
            ),
        ):
            preparation = self.activity_environment.run(
                prepare_managed_warehouse_view_translation_activity,
                str(job.id),
            )

        results = ManagedWarehouseViewTranslationResult.all_teams.filter(job=job)
        assert preparation.team_ids == (second_team.id,)
        assert list(results.values_list("saved_query_id", flat=True)) == [selected.id]
        assert not results.filter(saved_query_id=unselected.id).exists()

    def test_prepare_rejects_a_selected_view_outside_enabled_organization_teams(self) -> None:
        disabled_team = Team.objects.create(organization=self.organization)
        selected = DataWarehouseSavedQuery.objects.create(
            team=disabled_team,
            name="disabled_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
        )
        job = ManagedWarehouseViewTranslationJob.objects.create(
            organization=self.organization,
            scope=ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS,
            selected_saved_query_ids=[str(selected.id)],
        )

        with (
            patch(
                "products.managed_warehouse.backend.temporal.view_translation_workflow.get_ready_trino_catalog_name",
                return_value="managed_catalog",
            ),
            patch(
                "products.managed_warehouse.backend.temporal.view_translation_workflow.list_org_team_memberships",
                return_value=[_membership(disabled_team, enabled=False)],
            ),
            pytest.raises(ApplicationError, match="unavailable or are not enabled"),
        ):
            self.activity_environment.run(
                prepare_managed_warehouse_view_translation_activity,
                str(job.id),
            )

    def test_compile_continues_after_failures_and_preserves_saved_queries(self) -> None:
        saved_queries = [
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"kind": "HogQLQuery", "query": query},
            )
            for name, query in [
                ("bad_view", "SELECT bad"),
                ("good_view", "SELECT good"),
                ("changed_view", "SELECT original"),
            ]
        ]
        job = ManagedWarehouseViewTranslationJob.objects.create(
            organization=self.organization,
            status=ManagedWarehouseViewTranslationJob.Status.RUNNING,
        )
        for saved_query in saved_queries:
            ManagedWarehouseViewTranslationResult.all_teams.create(
                job=job,
                team=self.team,
                saved_query_id=saved_query.id,
                saved_query_name=saved_query.name,
                source_query_hash=source_query_hash(saved_query.query),
            )
        changed = saved_queries[2]
        changed.query = {"kind": "HogQLQuery", "query": "SELECT edited"}
        changed.save(update_fields=["query"])

        compile_kwargs: list[dict[str, object]] = []

        def compile_query(_team_id: int, query: HogQLQuery, **kwargs: object) -> TrinoCompiledQuery:
            compile_kwargs.append(kwargs)
            if query.query == "SELECT bad":
                raise ValueError("unsupported expression")
            return TrinoCompiledQuery(sql="SELECT translated", values={"value": 1}, hogql=query.query)

        with patch(
            "products.managed_warehouse.backend.temporal.view_translation_workflow.compile_hogql_to_trino_sql",
            side_effect=compile_query,
        ):
            self.activity_environment.run(
                compile_managed_warehouse_team_views_activity,
                str(job.id),
                self.team.id,
            )
        self.activity_environment.run(finalize_managed_warehouse_view_translation_activity, str(job.id))

        job.refresh_from_db()
        results = {
            result.saved_query_name: result
            for result in ManagedWarehouseViewTranslationResult.all_teams.filter(job=job)
        }
        assert results["bad_view"].status == ManagedWarehouseViewTranslationResult.Status.FAILED
        assert results["good_view"].status == ManagedWarehouseViewTranslationResult.Status.COMPILED
        assert results["good_view"].trino_sql == "SELECT translated"
        assert results["good_view"].normalized_hogql == "SELECT good"
        assert len(compile_kwargs) == 2
        assert all(kwargs["expansion_mode"] == TrinoExpansionMode.DJANGO for kwargs in compile_kwargs)
        assert all(kwargs["include_hogql"] is True for kwargs in compile_kwargs)
        assert results["changed_view"].status == ManagedWarehouseViewTranslationResult.Status.STALE
        assert DataWarehouseSavedQuery.objects.get(id=saved_queries[1].id).query == {
            "kind": "HogQLQuery",
            "query": "SELECT good",
        }
        assert job.status == ManagedWarehouseViewTranslationJob.Status.COMPLETED_WITH_ERRORS
        assert (job.compiled_count, job.failed_count, job.stale_count) == (1, 1, 1)


class TestManagedWarehouseViewTranslationStarter(BaseTest):
    def test_start_records_the_temporal_workflow(self) -> None:
        job = ManagedWarehouseViewTranslationJob.objects.create(organization=self.organization)
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock(return_value=MagicMock(run_id="run-123"))

        with patch(
            "products.managed_warehouse.backend.view_translation.sync_connect",
            return_value=temporal,
        ):
            start_managed_warehouse_view_translation(job.id, job.organization_id)

        job.refresh_from_db()
        assert job.workflow_id == f"managed-warehouse-view-translation/{job.id}"
        assert job.workflow_run_id == "run-123"
        call = temporal.start_workflow.call_args
        assert call.args == ("managed-warehouse.translate-views", str(job.id))
        assert call.kwargs["id"] == job.workflow_id
