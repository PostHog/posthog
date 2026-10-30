import pytest
from unittest import mock

from requests import ConnectionError

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.back_market import (
    BackMarketResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source import BackMarketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.backmarket import (
    BackMarketSourceConfig,
)


class TestBackMarketSource:
    def setup_method(self):
        self.source = BackMarketSource()
        self.team_id = 123
        self.config = BackMarketSourceConfig(api_token="token")

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        api_token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token"
        )
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.secret is True
        assert api_token_field.required is True

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((False, None), False, "Could not connect to Back Market with the provided API token"),
        ],
    )
    def test_validate_credentials(
        self, mock_return: tuple[bool, int | None], expected_valid: bool, expected_message: str | None
    ) -> None:
        status = mock_return[1]
        script = [ScriptedResponse(status=status)] if status is not None else always(ConnectionError("unavailable"))

        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].headers["authorization"] == "Basic token"

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is BackMarketResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source.back_market_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_back_market_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "date_modification"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_back_market_source.assert_called_once()
        kwargs = mock_back_market_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["incremental_field"] == "date_modification"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source.back_market_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_back_market_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "listings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_back_market_source.call_args.kwargs["db_incremental_field_last_value"] is None
