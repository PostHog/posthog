import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.iterable import (
    IterableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.source import IterableSource


class TestIterableSource:
    def setup_method(self):
        self.source = IterableSource()
        self.team_id = 123
        self.config = IterableSourceConfig(api_key="fake-key", region="us")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.iterable.com/api/campaigns",
            "403 Client Error: Forbidden for url: https://api.eu.iterable.com/api/templates",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "transient_error",
        [
            "500 Server Error for url: https://api.iterable.com/api/campaigns",
            "429 Client Error: Too Many Requests for url: https://api.iterable.com/api/campaigns",
            "Connection aborted: ReadTimeout for url: https://api.iterable.com/api/campaigns",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, transient_error):
        # Transient failures (5xx / 429 / timeouts) must stay retryable, not permanently fail the job.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in transient_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh(self):
        # No Iterable list endpoint exposes a verified server-side timestamp filter,
        # so everything is full refresh (no incremental / append).
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == INCREMENTAL_FIELDS[schema.name] == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Iterable API key for the selected data center"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.iterable.source.validate_iterable_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)
