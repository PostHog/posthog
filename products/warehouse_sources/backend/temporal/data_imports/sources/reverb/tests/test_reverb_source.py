import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source import ReverbSource

_INCREMENTAL_ENDPOINTS = {"Orders", "Payouts"}
_FULL_REFRESH_ENDPOINTS = {"Listings"}


class TestReverbSource:
    def setup_method(self):
        self.source = ReverbSource()
        self.team_id = 123
        self.config = ReverbSourceConfig(api_token="token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Reverb personal access token"),
            ((False, 403), False, "Could not connect to Reverb with the provided personal access token"),
            ((False, None), False, "Could not connect to Reverb with the provided personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.validate_reverb_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token", "3.0")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.reverb_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_reverb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_reverb_source.assert_called_once()
        kwargs = mock_reverb_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "Orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["api_version"] == "3.0"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.reverb_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_reverb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Listings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_reverb_source.call_args.kwargs["db_incremental_field_last_value"] is None
