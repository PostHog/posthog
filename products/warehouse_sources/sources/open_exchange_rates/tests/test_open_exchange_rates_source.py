from datetime import UTC, datetime, timedelta

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openexchangerates import (
    OpenExchangeRatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source import (
    OpenExchangeRatesSource,
)


class TestOpenExchangeRatesSource:
    def setup_method(self) -> None:
        self.source = OpenExchangeRatesSource()
        self.team_id = 123
        self.config = OpenExchangeRatesSourceConfig(app_id="oxr-test", base_currency="USD", start_date=None)

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.path for request in network.requests_log] == ["/api/usage.json"]
        assert network.requests_log[0].headers["authorization"] == "Token oxr-test"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source.open_exchange_rates_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "historical"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["app_id"] == "oxr-test"
        assert kwargs["endpoint"] == "historical"
        assert kwargs["base_currency"] == "USD"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        start = datetime.now(tz=UTC).date() - timedelta(days=2)
        config = OpenExchangeRatesSourceConfig(app_id="oxr-test", base_currency="USD", start_date=start.isoformat())
        result = SourceDriver(self.source, config).run(
            "historical",
            always(ScriptedResponse(json={"base": "USD", "rates": {"EUR": 0.9}})),
            should_use_incremental_field=False,
            db_incremental_field_last_value=(start + timedelta(days=1)).isoformat(),
        )

        assert result.raised is None
        # A non-incremental sync must not pass a stale watermark down to the transport.
        assert result.paths[0] == f"/api/historical/{start.isoformat()}.json"
