import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.source import CloudflareSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflare import (
    CloudflareSourceConfig,
)


class TestCloudflareSource:
    def setup_method(self):
        self.source = CloudflareSource()
        self.team_id = 123
        self.config = CloudflareSourceConfig(api_token="api-token")

    def test_get_schemas_only_advertise_incremental_where_the_api_filters_server_side(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert {name for name, schema in schemas.items() if schema.supports_incremental} == set(INCREMENTAL_FIELDS)
        assert [field["field"] for field in schemas["audit_logs"].incremental_fields] == ["when"]
        assert all(
            schema.incremental_fields == [] for name, schema in schemas.items() if name not in INCREMENTAL_FIELDS
        )

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_substring",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Cloudflare API token"),
            ((False, 403), False, "Invalid Cloudflare API token"),
            ((False, None), False, "Couldn't reach Cloudflare"),
            ((False, 500), False, "Couldn't reach Cloudflare"),
            ((False, 429), False, "Couldn't reach Cloudflare"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.source.validate_cloudflare_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_substring):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_substring is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert expected_substring in error_message
        mock_validate.assert_called_once_with(self.config.api_token)
