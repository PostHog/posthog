import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plivo import PlivoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source import PlivoSource


class TestPlivoSource:
    def setup_method(self):
        self.source = PlivoSource()
        self.team_id = 123
        self.config = PlivoSourceConfig(auth_id="MA123", auth_token="token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Plivo Auth ID or Auth Token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source.validate_plivo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("MA123", "token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source.plivo_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_plivo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-01 00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A stale cursor must not narrow a full refresh to a partial window.
        assert mock_plivo_source.call_args.kwargs["db_incremental_field_last_value"] is None
