import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.justcall import (
    JustCallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source import JustCallSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source"


class TestJustCallSource:
    def setup_method(self):
        self.source = JustCallSource()
        self.team_id = 123
        self.config = JustCallSourceConfig(api_key="key", api_secret="secret")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.justcall.io/v2.1/calls?page=0",
            "403 Client Error: Forbidden for url: https://api.justcall.io/v2.1/texts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.justcall.io/v2.1/calls",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_only_time_filterable_endpoints_support_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        # Only calls, texts, and sales dialer calls expose JustCall's from_datetime filter.
        assert incremental == {"calls", "texts", "sales_dialer_calls"}

        assert schemas["calls"].incremental_fields == INCREMENTAL_FIELDS["calls"]
        assert schemas["contacts"].incremental_fields == []
        assert schemas["contacts"].supports_append is False

    def test_lists_tables_without_credentials(self):
        # The endpoint catalog is static (no I/O), so it's safe to render in public docs.
        assert JustCallSource.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid JustCall API credentials"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_justcall_credentials")
    def test_validate_credentials(self, mock_validate, probe_result, expected_valid, expected_message):
        mock_validate.return_value = probe_result

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.api_secret)
