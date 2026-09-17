import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source import CodecovSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codecov import (
    CodecovSourceConfig,
)

_INCREMENTAL_ENDPOINTS = {"commits", "coverage_trend"}
_FULL_REFRESH_ENDPOINTS = {"repos", "branches", "pulls", "flags", "components"}


class TestCodecovSource:
    def setup_method(self):
        self.source = CodecovSource()
        self.team_id = 123
        self.config = CodecovSourceConfig(owner_username="acme", api_token="token")

    def test_connection_host_fields_force_secret_reentry_on_scope_change(self):
        # Retargeting the git provider, owner, or repository allow-list reuses the stored token
        # against different Codecov resources, so the update serializer must require re-entry.
        assert self.source.connection_host_fields == ["service", "owner_username", "repositories"]

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["timestamp"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []
        # Incremental syncs re-pull boundary rows that only merge dedupes, so append stays off.
        for schema in schemas.values():
            assert schema.supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["commits"])
        assert [s.name for s in schemas] == ["commits"]

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.codecov.io/api/v2/github/acme/repos?page_size=500",
            "403 Client Error: Forbidden for url: https://api.codecov.io/api/v2/github/acme/repos/r1/commits",
            "404 Client Error: Not Found for url: https://api.codecov.io/api/v2/github/acme/repos?page_size=500",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.codecov.io/api/v2/github/acme/repos",
            "500 Server Error: Internal Server Error for url: https://api.codecov.io/api/v2/github/acme/repos",
            "HTTPSConnectionPool(host='api.codecov.io', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Codecov API token"),
            ((False, 404), False, "Owner 'acme' not found on Codecov for the selected git provider"),
            ((False, None), False, "Could not connect to Codecov with the provided credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source.validate_codecov_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
