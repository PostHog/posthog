from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.ruddr._config import RuddrSourceConfig
from products.warehouse_sources.sources.ruddr.source import RuddrSource


class TestRuddrSource:
    def setup_method(self) -> None:
        self.source = RuddrSource()
        self.team_id = 123
        self.config = RuddrSourceConfig(api_key="ruddr-key")

    @mock.patch("products.warehouse_sources.sources.ruddr.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in ruddr.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Ruddr API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("ruddr-key")
        assert result == (False, "Invalid Ruddr API key")

    @parameterized.expand(
        [
            ("incremental", True, "modifiedAt", "2025-02-05T20:47:03.284Z"),
            ("full_refresh_drops_stale_watermark", False, None, None),
        ]
    )
    @mock.patch("products.warehouse_sources.sources.ruddr.source.ruddr_source")
    def test_source_for_pipeline_plumbs_arguments(
        self,
        _name: str,
        use_incremental: bool,
        expected_field: str | None,
        expected_last_value: Any,
        mock_source: mock.MagicMock,
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.should_use_incremental_field = use_incremental
        inputs.incremental_field = "modifiedAt"
        inputs.db_incremental_field_last_value = "2025-02-05T20:47:03.284Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "ruddr-key"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["incremental_field"] == expected_field
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
