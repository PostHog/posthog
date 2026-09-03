import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plivo import PlivoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source import PlivoSource


class TestPlivoSource:
    def setup_method(self):
        self.source = PlivoSource()
        self.team_id = 123
        self.config = PlivoSourceConfig(auth_id="MA123", auth_token="token")

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Plivo"
        assert config.label == "Plivo"
        assert config.category == DataWarehouseSourceCategory.COMMUNICATION
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source must be visible — regressing to the scaffold's hidden state would
        # remove the connector from every user's wizard.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/plivo.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/plivo"

    def test_get_schemas_incremental_support(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in ("messages", "calls", "recordings"):
            assert schemas[name].supports_incremental is True, name
            assert schemas[name].incremental_fields == INCREMENTAL_FIELDS[name]
        # The application list has no server-side time filter — full refresh only.
        assert schemas["applications"].supports_incremental is False
        assert schemas["applications"].supports_append is False

    @pytest.mark.parametrize(
        "observed_error, is_non_retryable",
        [
            ("401 Client Error: Unauthorized for url: https://api.plivo.com/v1/Account/MA123/Message/", True),
            ("403 Client Error: Forbidden for url: https://api.plivo.com/v1/Account/MA123/Call/", True),
            ("500 Server Error: Internal Server Error for url: https://api.plivo.com/v1/Account/MA123/Call/", False),
            ("429 Client Error: Too Many Requests for url: https://api.plivo.com/v1/Account/MA123/Message/", False),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers", False),
        ],
    )
    def test_non_retryable_errors(self, observed_error, is_non_retryable):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors) is is_non_retryable

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
