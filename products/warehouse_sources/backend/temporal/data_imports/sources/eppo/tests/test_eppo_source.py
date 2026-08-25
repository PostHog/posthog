import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.source import EppoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eppo import EppoSourceConfig

# Only "Experiments" documents a server-side timestamp filter (created_since/updated_since).
_INCREMENTAL_ENDPOINTS = {"Experiments"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestEppoSource:
    def setup_method(self):
        self.source = EppoSource()
        self.team_id = 123
        self.config = EppoSourceConfig(api_key="key")

    def test_api_docs_url_is_set(self):
        assert self.source.api_docs_url == "https://eppo.cloud/api/docs"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://eppo.cloud/api/v1/experiments?limit=100",
            "403 Client Error: Forbidden for url: https://eppo.cloud/api/v1/experiments?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://eppo.cloud/api/v1/experiments",
            "500 Server Error: Internal Server Error for url: https://eppo.cloud/api/v1/experiments",
            "HTTPSConnectionPool(host='eppo.cloud', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_message",
        [
            ((True, 200), None, True, None),
            ((False, 401), None, False, "Invalid Eppo API key"),
            # A valid key that lacks scope for one resource must not block source-create.
            ((False, 403), None, True, None),
            # ...but a per-table scope check on a specific schema should still surface it.
            ((False, 403), "Experiments", False, "Invalid Eppo API key"),
            ((False, None), None, False, "Invalid Eppo API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.eppo.source.validate_eppo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, schema_name, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
