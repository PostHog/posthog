import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.outbrain import (
    OutbrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source import OutbrainSource


class TestOutbrainSource:
    def setup_method(self):
        self.source = OutbrainSource()
        self.team_id = 123
        self.config = OutbrainSourceConfig(username="u@x.com", password="pw")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.outbrain.com/amplify/v0.1/login",
            "403 Client Error: Forbidden for url: https://api.outbrain.com/amplify/v0.1/marketers",
            "400 Client Error: Bad Request for url: https://api.outbrain.com/amplify/v0.1/marketers/marketer/campaigns?limit=100&offset=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.outbrain.com/amplify/v0.1/marketers",
            # Mid-sync 401s on data endpoints are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.outbrain.com/amplify/v0.1/marketers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the daily periodic report has a real server-side date filter
        # with a per-row date.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"marketer_performance_daily"}
        assert (
            schemas["marketer_performance_daily"].incremental_fields == INCREMENTAL_FIELDS["marketer_performance_daily"]
        )
        assert schemas["campaigns"].incremental_fields == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source.validate_outbrain_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Outbrain credentials"
        mock_validate.assert_called_once_with("u@x.com", "pw")
