from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from products.revenue_analytics.backend.views.orchestrator import SUPPORTED_SOURCES
from products.revenue_analytics.backend.warehouse_view_sync import sync_revenue_analytics_views
from products.warehouse_sources.backend.facade.hooks import RevenueViewSyncInput


def _make_sync_input() -> RevenueViewSyncInput:
    return RevenueViewSyncInput(
        team_id=1,
        source_id=uuid4(),
        source_type=SUPPORTED_SOURCES[0],
        schema_name="Charge",
    )


class TestWarehouseViewSync:
    @parameterized.expand([("operational", OperationalError), ("interface", InterfaceError)])
    @patch("products.revenue_analytics.backend.warehouse_view_sync.capture_exception")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.list_revenue_source_settings")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.DataWarehouseManagedViewSet")
    def test_transient_connection_error_is_not_captured(
        self,
        _name: str,
        error_cls: type[Exception],
        mock_viewset: MagicMock,
        mock_sources: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        mock_sources.return_value = [MagicMock(enabled=True)]
        mock_viewset.objects.filter.return_value.first.side_effect = error_cls("server closed the connection")

        sync_revenue_analytics_views(_make_sync_input())

        mock_capture.assert_not_called()

    @patch("products.revenue_analytics.backend.warehouse_view_sync.capture_exception")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.list_revenue_source_settings")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.DataWarehouseManagedViewSet")
    def test_unexpected_error_is_captured(
        self, mock_viewset: MagicMock, mock_sources: MagicMock, mock_capture: MagicMock
    ) -> None:
        error = ValueError("something actually broke")
        mock_sources.return_value = [MagicMock(enabled=True)]
        mock_viewset.objects.filter.return_value.first.side_effect = error

        sync_revenue_analytics_views(_make_sync_input())

        mock_capture.assert_called_once_with(error)

    @patch("products.revenue_analytics.backend.warehouse_view_sync.list_revenue_source_settings")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.DataWarehouseManagedViewSet")
    def test_deleted_source_reconciles_managed_views(self, mock_viewset: MagicMock, mock_sources: MagicMock) -> None:
        mock_sources.side_effect = lambda *args, include_deleted=False, **kwargs: (
            [MagicMock(deleted=True, enabled=False)] if include_deleted else []
        )
        managed_viewset = mock_viewset.objects.filter.return_value.first.return_value

        sync_revenue_analytics_views(_make_sync_input())

        managed_viewset.sync_views.assert_called_once_with()
