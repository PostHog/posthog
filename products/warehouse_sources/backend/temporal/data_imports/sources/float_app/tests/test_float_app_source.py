import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    ENDPOINTS,
    FLOAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.source import FloatAppSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.floatapp import (
    FloatAppSourceConfig,
)

_CURSOR_ENDPOINTS = {"deleted_tasks", "deleted_timeoffs", "deleted_logged_time"}


class TestFloatAppSource:
    def setup_method(self):
        self.source = FloatAppSource()
        self.team_id = 123
        self.config = FloatAppSourceConfig(api_key="key")

    def test_get_schemas_are_all_full_refresh_with_mapped_primary_keys(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            # Float exposes no server-side incremental filter, so every stream is full refresh.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == FLOAT_ENDPOINTS[name].primary_keys

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Float access token"),
            ((False, 403), False, "Could not connect to Float with the provided access token"),
            ((False, None), False, "Could not connect to Float with the provided access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.float_app.source.validate_float_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
