import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source import EventeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventee import (
    EventeeSourceConfig,
)


class TestEventeeSource:
    def setup_method(self):
        self.source = EventeeSource()
        self.team_id = 123
        self.config = EventeeSourceConfig(api_key="tok")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.eventee.com/public/v1/content",
            "403 Client Error: Forbidden for url: https://api.eventee.com/public/v1/groups",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.eventee.com/public/v1/reviews",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials(self):
        # Static catalog with no I/O — required for the public docs Supported tables section to render.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Eventee API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source.validate_eventee_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("tok")
