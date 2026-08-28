import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.source import DopplerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doppler import (
    DopplerSourceConfig,
)

# The activity log is the only endpoint with a usable incremental cursor (append-only,
# newest-first); everything else is full refresh.
_INCREMENTAL_ENDPOINTS = {"activity_logs"}


class TestDopplerSource:
    def setup_method(self):
        self.source = DopplerSource()
        self.team_id = 123
        self.config = DopplerSourceConfig(api_token="dp.pt.token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.doppler.com/v3/logs?page=1&per_page=20",
            "403 Client Error: Forbidden for url: https://api.doppler.com/v3/projects?page=1&per_page=20",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.doppler.com/v3/logs",
            "500 Server Error: Internal Server Error for url: https://api.doppler.com/v3/logs",
            "HTTPSConnectionPool(host='api.doppler.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            expected_incremental = name in _INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected_incremental
            # Crash-resume can re-yield the last batch, so append (no dedupe) is never offered.
            assert schema.supports_append is False
            if expected_incremental:
                assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
            else:
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["activity_logs"])
        assert [schema.name for schema in schemas] == ["activity_logs"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Doppler API token"),
            ((False, 403), False, "Could not connect to Doppler with the provided API token"),
            ((False, None), False, "Could not connect to Doppler with the provided API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.doppler.source.validate_doppler_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("dp.pt.token")
