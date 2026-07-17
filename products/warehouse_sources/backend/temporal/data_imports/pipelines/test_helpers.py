from datetime import date

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import structlog

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
    initial_datetime,
    sync_revenue_analytics_views,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
)
from products.warehouse_sources.backend.types import (
    DataWarehouseManagedViewSetKind,
    ExternalDataSourceType,
    IncrementalFieldType,
)

PATH = "products.data_modeling.backend.models.datawarehouse_saved_query"


@pytest.mark.parametrize(
    "field_type,expected",
    [
        # Date and XID are the inclusive (`>=`) cases.
        (IncrementalFieldType.Date, ">="),
        (IncrementalFieldType.XID, ">="),
        (IncrementalFieldType.DateTime, ">"),
        (IncrementalFieldType.Timestamp, ">"),
        (IncrementalFieldType.Integer, ">"),
        (IncrementalFieldType.Numeric, ">"),
        (IncrementalFieldType.ObjectID, ">"),
    ],
)
def test_incremental_type_to_operator(field_type: IncrementalFieldType, expected: str) -> None:
    assert incremental_type_to_operator(field_type) == expected


@pytest.mark.parametrize(
    "field_type,expected",
    [
        (IncrementalFieldType.XID, 0),
        (IncrementalFieldType.Integer, 0),
        (IncrementalFieldType.Numeric, 0),
        (IncrementalFieldType.ObjectID, "000000000000000000000000"),
        (IncrementalFieldType.DateTime, initial_datetime),
        (IncrementalFieldType.Timestamp, initial_datetime),
        (IncrementalFieldType.Date, date(1970, 1, 1)),
    ],
)
def test_incremental_type_to_initial_value(field_type: IncrementalFieldType, expected: object) -> None:
    assert incremental_type_to_initial_value(field_type) == expected


class TestSyncRevenueAnalyticsViews(BaseTest):
    """Tests for the sync_revenue_analytics_views function
    that should be called after run_post_load_operations completes.
    """

    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src_stripe_2",
            connection_id="conn_2",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self.credential = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        self.managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

    @patch(f"{PATH}.DataWarehouseSavedQuery.schedule_materialization")
    def test_sync_called_for_stripe_source_with_revenue_analytics_enabled(self, _):
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=None,
            should_sync=True,
        )

        with patch.object(DataWarehouseManagedViewSet, "sync_views") as mock_sync:
            sync_revenue_analytics_views(schema, self.source)
            mock_sync.assert_called_once()

    @patch(f"{PATH}.DataWarehouseSavedQuery.schedule_materialization")
    def test_sync_skipped_for_non_stripe_source(self, _):
        self.source.source_type = "Salesforce"
        self.source.save()

        schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Account",
            source=self.source,
            table=None,
            should_sync=True,
        )

        with patch.object(DataWarehouseManagedViewSet, "sync_views") as mock_sync:
            sync_revenue_analytics_views(schema, self.source)
            mock_sync.assert_not_called()

    @patch(f"{PATH}.DataWarehouseSavedQuery.schedule_materialization")
    def test_sync_skipped_when_revenue_analytics_disabled(self, _):
        self.source.revenue_analytics_config.enabled = False
        self.source.revenue_analytics_config.save()

        schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=None,
            should_sync=True,
        )

        with patch.object(DataWarehouseManagedViewSet, "sync_views") as mock_sync:
            sync_revenue_analytics_views(schema, self.source)
            mock_sync.assert_not_called()

    @patch(f"{PATH}.DataWarehouseSavedQuery.schedule_materialization")
    def test_sync_skipped_when_no_managed_viewset_exists(self, _):
        self.managed_viewset.delete()

        schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=None,
            should_sync=True,
        )

        with structlog.testing.capture_logs() as logs:
            sync_revenue_analytics_views(schema, self.source)

        assert any(log["event"] == "sync_revenue_analytics_views_skipped_no_viewset" for log in logs)

    @patch(f"{PATH}.DataWarehouseSavedQuery.schedule_materialization")
    def test_sync_does_not_crash_pipeline_on_error(self, _):
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=None,
            should_sync=True,
        )

        with (
            patch.object(DataWarehouseManagedViewSet, "sync_views", side_effect=Exception("boom")),
            structlog.testing.capture_logs() as logs,
        ):
            sync_revenue_analytics_views(schema, self.source)

        assert any(log["event"] == "sync_revenue_analytics_views_failed" for log in logs)
