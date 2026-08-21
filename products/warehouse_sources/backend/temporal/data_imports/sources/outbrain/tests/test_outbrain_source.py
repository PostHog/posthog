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
