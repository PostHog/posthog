import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.taboola import (
    TaboolaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source import TaboolaSource


class TestTaboolaSource:
    def setup_method(self):
        self.source = TaboolaSource()
        self.team_id = 123
        self.config = TaboolaSourceConfig(client_id="cid", client_secret="sec", account_id="acct")

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the date-windowed report has a real server-side date filter.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"campaign_summary_by_day"}
        assert schemas["campaign_summary_by_day"].incremental_fields == INCREMENTAL_FIELDS["campaign_summary_by_day"]
        assert schemas["campaigns"].incremental_fields == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source.validate_taboola_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Taboola credentials"
        mock_validate.assert_called_once_with("cid", "sec")
