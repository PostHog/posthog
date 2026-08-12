from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.engineering_analytics.backend.logic.sources import WORKFLOW_JOBS_SCHEMA, WORKFLOW_RUNS_SCHEMA
from products.engineering_analytics.backend.warehouse_view_sync import sync_engineering_analytics_views
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

PREFIX = "myprefix"


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

    @patch.object(DataWarehouseManagedViewSet, "sync_views")
    def test_creates_viewset_and_syncs_for_qualifying_source(self, mock_sync) -> None:
        source = self._qualifying_source()
        schema = ExternalDataSchema.objects.get(source=source, name=WORKFLOW_JOBS_SCHEMA)

        sync_engineering_analytics_views(schema, source)

        mock_sync.assert_called_once()
        assert self._has_viewset()

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
