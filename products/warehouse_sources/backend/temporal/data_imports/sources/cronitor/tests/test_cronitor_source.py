import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.source import CronitorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cronitor import (
    CronitorSourceConfig,
)

# Only the metrics API exposes a server-side time filter (start/end); everything else is full refresh.
_INCREMENTAL_ENDPOINTS = {"metrics"}
_FULL_REFRESH_ENDPOINTS = {"monitors", "invocations"}


class TestCronitorSource:
    def setup_method(self):
        self.source = CronitorSource()
        self.team_id = 123
        self.config = CronitorSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://cronitor.io/api/monitors?page=1&pageSize=50&sort=created",
            "403 Client Error: Forbidden for url: https://cronitor.io/api/metrics?monitor=job-a",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://cronitor.io/api/monitors",
            "500 Server Error: Internal Server Error for url: https://cronitor.io/api/monitors",
            "HTTPSConnectionPool(host='cronitor.io', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["stamp"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["metrics"])
        assert len(schemas) == 1
        assert schemas[0].name == "metrics"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Cronitor API key. Make sure the key has the monitor:read scope."),
            ((False, 403), False, "Invalid Cronitor API key. Make sure the key has the monitor:read scope."),
            ((False, None), False, "Could not connect to Cronitor with the provided API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.source.validate_cronitor_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
