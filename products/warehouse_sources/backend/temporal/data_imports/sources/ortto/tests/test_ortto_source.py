import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ortto import OrttoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source import OrttoSource


class TestOrttoSource:
    def setup_method(self):
        self.source = OrttoSource()
        self.team_id = 123
        self.config = OrttoSourceConfig(api_key="key", region="eu")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.ap3api.com/v1/person/get",
            "403 Client Error: Forbidden for url: https://api.eu.ap3api.com/v1/accounts/get",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://api.ap3api.com/v1/person/get"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint exposes a server-side updated-since filter — everything full refresh.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source.validate_ortto_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Ortto credentials"
        mock_validate.assert_called_once_with("eu", "key")
