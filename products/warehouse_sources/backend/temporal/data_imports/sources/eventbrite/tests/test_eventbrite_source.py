import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.settings import INCREMENTAL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source import EventbriteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventbrite import (
    EventbriteSourceConfig,
)


class TestEventbriteSource:
    def setup_method(self):
        self.source = EventbriteSource()
        self.team_id = 123
        self.config = EventbriteSourceConfig(api_token="test-token")

    def test_non_retryable_errors_matches_observed_error_message(self):
        # Eventbrite's API sends the HTTP reason phrase in all caps, not the title-case wording
        # `requests.raise_for_status()` generates for other vendors — the dict key above must still
        # match it.
        observed_error = (
            "401 Client Error: UNAUTHORIZED for url: https://www.eventbriteapi.com/v3/users/me/organizations/"
        )
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert error_message_matches(observed_error, non_retryable_errors)

    def test_get_schemas_incremental_endpoints_are_orders_and_attendees(self):
        assert set(INCREMENTAL_ENDPOINTS) == {"orders", "attendees"}

    @pytest.mark.parametrize(
        "credentials_valid, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Eventbrite private token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source.validate_eventbrite_credentials"
    )
    def test_validate_credentials(self, mock_validate, credentials_valid, expected_valid, expected_message):
        mock_validate.return_value = credentials_valid

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)
