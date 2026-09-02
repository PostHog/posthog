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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.float.com/v3/people?per-page=200&page=1",
            "403 Client Error: Forbidden for url: https://api.float.com/v3/logged-time?per-page=200&page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.float.com/v3/people",
            "500 Server Error: Internal Server Error for url: https://api.float.com/v3/people",
            "HTTPSConnectionPool(host='api.float.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_all_full_refresh_with_mapped_primary_keys(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            # Float exposes no server-side incremental filter, so every stream is full refresh.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == FLOAT_ENDPOINTS[name].primary_keys

    def test_delete_log_endpoints_are_off_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        for name in _CURSOR_ENDPOINTS:
            assert schemas[name].should_sync_default is False
        assert schemas["people"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["people"])
        assert [s.name for s in schemas] == ["people"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)
        # Full refresh is the only advertised sync method.
        assert all(table["sync_methods"] == ["Full refresh"] for table in documented)

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
