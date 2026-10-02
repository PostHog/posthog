from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.logic.sources import (
    DEPOT_JOB_ATTEMPTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.logic.stored_views import is_in_use, mark_in_use
from products.engineering_analytics.backend.logic.views import ci_jobs, ci_runs, job_costs, pr_friction
from products.engineering_analytics.backend.tests._github_fixtures import (
    connect_github_source_without_data,
    create_depot_source,
)
from products.engineering_analytics.backend.tests._logic_helpers import _RUN_QUERY, _resp
from products.engineering_analytics.backend.warehouse_view_sync import sync_engineering_analytics_views
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

PREFIX = "myprefix"
_STORED_VIEWS = "products.engineering_analytics.backend.logic.stored_views"


class TestSyncEngineeringAnalyticsViews(BaseTest):
    def _github_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh",
            connection_id="gh",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix=PREFIX,
        )

    def _table(self, name: str, source: ExternalDataSource) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            url_pattern="",
            external_data_source=source,
            columns={},
        )

    def _schema(self, source: ExternalDataSource, name: str, table: DataWarehouseTable | None) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team=self.team, source=source, name=name, table=table, should_sync=True
        )

    def _qualifying_source(self) -> ExternalDataSource:
        source = self._github_source()
        self._schema(source, WORKFLOW_RUNS_SCHEMA, self._table(f"{PREFIX}github_workflow_runs", source))
        self._schema(source, WORKFLOW_JOBS_SCHEMA, self._table(f"{PREFIX}github_workflow_jobs", source))
        return source

    def _has_viewset(self) -> bool:
        return DataWarehouseManagedViewSet.objects.filter(
            team=self.team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
        ).exists()

    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_noop_for_non_github_source(self, mock_sync) -> None:
        source = self._qualifying_source()
        source.source_type = ExternalDataSourceType.STRIPE
        source.save()
        schema = ExternalDataSchema.objects.get(source=source, name=WORKFLOW_JOBS_SCHEMA)

        sync_engineering_analytics_views(schema, source)

        mock_sync.assert_not_called()
        assert not self._has_viewset()

    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_noop_for_irrelevant_schema(self, mock_sync) -> None:
        source = self._qualifying_source()
        schema = self._schema(source, "pull_requests", self._table(f"{PREFIX}github_pull_requests", source))

        sync_engineering_analytics_views(schema, source)

        mock_sync.assert_not_called()
        assert not self._has_viewset()

    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_noop_when_jobs_endpoint_not_synced(self, mock_sync) -> None:
        # A GitHub source with only workflow_runs synced has no view to expose yet — don't even
        # create the viewset row until both endpoints exist.
        source = self._github_source()
        schema = self._schema(source, WORKFLOW_RUNS_SCHEMA, self._table(f"{PREFIX}github_workflow_runs", source))

        sync_engineering_analytics_views(schema, source)

        mock_sync.assert_not_called()
        assert not self._has_viewset()

    @parameterized.expand([("github_jobs", False), ("depot_attempts", True)])
    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_creates_viewset_and_syncs_for_qualifying_source(
        self, _name: str, from_depot: bool, mock_sync: MagicMock
    ) -> None:
        source = self._qualifying_source()
        schema = ExternalDataSchema.objects.get(source=source, name=WORKFLOW_JOBS_SCHEMA)
        if from_depot:
            # A Depot load adds its attempts to the views' SQL, so it must re-sync them too.
            source = create_depot_source(self.team, prefix=PREFIX)
            schema = self._schema(source, DEPOT_JOB_ATTEMPTS_SCHEMA, self._table(f"{PREFIX}depot_job_attempts", source))

        sync_engineering_analytics_views(schema, source)

        mock_sync.assert_called_once()
        assert self._has_viewset()

    def _create_views(self) -> None:
        viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
        )
        for name, is_materialized in (
            (ci_runs.VIEW_NAME, True),
            (ci_jobs.VIEW_NAME, True),
            # The friction replay is too heavy to run on every load, and a query-time view has no table.
            (pr_friction.VIEW_NAME, True),
            (job_costs.VIEW_NAME, False),
        ):
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"kind": "HogQLQuery", "query": "SELECT 1"},
                managed_viewset=viewset,
                is_materialized=is_materialized,
            )

    @parameterized.expand(
        [
            ("rebuild_starts", True, None),
            ("rebuild_cannot_start", True, RuntimeError("temporal is down")),
            # Nobody read the product lately, so a rebuild would spend compute on a table nobody reads.
            ("product_idle", False, None),
        ]
    )
    @patch(f"{_STORED_VIEWS}.capture_exception")
    @patch(f"{_STORED_VIEWS}.data_modeling.materialize_saved_query")
    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_load_rebuilds_the_stored_views_while_the_product_is_in_use(
        self,
        _name: str,
        in_use: bool,
        error: Exception | None,
        _mock_sync: MagicMock,
        mock_materialize: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        cache.clear()
        if in_use:
            mark_in_use(self.team.pk)
        source = self._qualifying_source()
        schema = ExternalDataSchema.objects.get(source=source, name=WORKFLOW_JOBS_SCHEMA)
        self._create_views()
        mock_materialize.side_effect = error

        sync_engineering_analytics_views(schema, source)

        rebuilt = {ci_runs.VIEW_NAME, ci_jobs.VIEW_NAME} if in_use else set()
        assert {call.args[0].name for call in mock_materialize.call_args_list} == rebuilt
        # A load is not a person asking for a retry, so it must not lift the suspension of a failing view.
        assert all(call.kwargs == {"resume": False} for call in mock_materialize.call_args_list)
        assert mock_capture.call_count == (2 if error else 0)

    @patch(f"{_STORED_VIEWS}.data_modeling.materialize_saved_query")
    def test_only_the_first_read_after_an_idle_spell_starts_a_rebuild(self, mock_materialize: MagicMock) -> None:
        cache.clear()
        self._create_views()

        mark_in_use(self.team.pk)
        mark_in_use(self.team.pk)

        assert sorted(call.args[0].name for call in mock_materialize.call_args_list) == sorted(
            [ci_runs.VIEW_NAME, ci_jobs.VIEW_NAME]
        )

    @parameterized.expand([("person_or_agent", True), ("system", False)])
    def test_only_a_read_with_a_user_keeps_the_product_in_use(self, _name: str, has_user: bool) -> None:
        cache.clear()
        connect_github_source_without_data(self.team)
        user_access_control = UserAccessControl(user=self.user, team=self.team) if has_user else None

        with patch(_RUN_QUERY, return_value=_resp([(0, 0, 0, 0)])):
            api.get_ci_cards(team=self.team, user_access_control=user_access_control)

        assert is_in_use(self.team.pk) is has_user

    @parameterized.expand([("operational", OperationalError), ("interface", InterfaceError)])
    @patch("products.engineering_analytics.backend.warehouse_view_sync.capture_exception")
    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_transient_db_error_is_not_captured(self, _name, error_cls, mock_sync, mock_capture) -> None:
        mock_sync.side_effect = error_cls("server closed the connection")
        source = self._qualifying_source()
        schema = ExternalDataSchema.objects.get(source=source, name=WORKFLOW_JOBS_SCHEMA)

        sync_engineering_analytics_views(schema, source)

        mock_capture.assert_not_called()

    @patch("products.engineering_analytics.backend.warehouse_view_sync.capture_exception")
    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_unexpected_error_is_captured(self, mock_sync, mock_capture) -> None:
        error = ValueError("something actually broke")
        mock_sync.side_effect = error
        source = self._qualifying_source()
        schema = ExternalDataSchema.objects.get(source=source, name=WORKFLOW_JOBS_SCHEMA)

        sync_engineering_analytics_views(schema, source)

        mock_capture.assert_called_once_with(error)
