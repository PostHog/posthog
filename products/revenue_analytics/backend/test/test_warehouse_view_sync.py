from unittest.mock import MagicMock, patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from products.revenue_analytics.backend.views.orchestrator import SUPPORTED_SOURCES
from products.revenue_analytics.backend.warehouse_view_sync import sync_revenue_analytics_views


def _make_schema_and_source() -> tuple[MagicMock, MagicMock]:
    schema = MagicMock()
    schema.team_id = 1
    source = MagicMock()
    source.revenue_analytics_config_safe.enabled = True
    source.source_type = SUPPORTED_SOURCES[0]
    return schema, source


class TestWarehouseViewSync:
    @parameterized.expand([("operational", OperationalError), ("interface", InterfaceError)])
    @patch("products.revenue_analytics.backend.warehouse_view_sync.capture_exception")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.DataWarehouseManagedViewSet")
    def test_transient_connection_error_is_not_captured(
        self, _name: str, error_cls: type[Exception], mock_viewset: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_viewset.objects.filter.return_value.first.side_effect = error_cls("server closed the connection")
        schema, source = _make_schema_and_source()

        sync_revenue_analytics_views(schema, source)

        mock_capture.assert_not_called()

    @patch("products.revenue_analytics.backend.warehouse_view_sync.capture_exception")
    @patch("products.revenue_analytics.backend.warehouse_view_sync.DataWarehouseManagedViewSet")
    def test_unexpected_error_is_captured(self, mock_viewset: MagicMock, mock_capture: MagicMock) -> None:
        error = ValueError("something actually broke")
        mock_viewset.objects.filter.return_value.first.side_effect = error
        schema, source = _make_schema_and_source()

        sync_revenue_analytics_views(schema, source)

        mock_capture.assert_called_once_with(error)
