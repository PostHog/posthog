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

    def test_only_time_filterable_endpoints_support_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        # Only calls, texts, and sales dialer calls expose JustCall's from_datetime filter.
        assert incremental == {"calls", "texts", "sales_dialer_calls"}

        assert schemas["calls"].incremental_fields == INCREMENTAL_FIELDS["calls"]
        assert schemas["contacts"].incremental_fields == []
        assert schemas["contacts"].supports_append is False

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
