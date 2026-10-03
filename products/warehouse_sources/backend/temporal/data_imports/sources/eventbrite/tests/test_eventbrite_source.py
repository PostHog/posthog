import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source import EventbriteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventbrite import (
    EventbriteSourceConfig,
)


class TestEventbriteSource:
    def setup_method(self):
        self.source = EventbriteSource()
        self.team_id = 123
        self.config = EventbriteSourceConfig(api_token="test-token")

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://www.eventbriteapi.com",
            "403 Client Error: Forbidden for url: https://www.eventbriteapi.com",
        ],
    )
    def test_non_retryable_errors_includes_eventbrite_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self):
        # Eventbrite's API sends the HTTP reason phrase in all caps, not the title-case wording
        # `requests.raise_for_status()` generates for other vendors — the dict key above must still
        # match it.
        observed_error = (
            "401 Client Error: UNAUTHORIZED for url: https://www.eventbriteapi.com/v3/users/me/organizations/"
        )
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert error_message_matches(observed_error, non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://a.klaviyo.com/api/accounts",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags_match_settings(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        for schema in schemas:
            expected = schema.name in INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected
            if expected:
                assert schema.incremental_fields, f"{schema.name} should advertise incremental fields"
            else:
                assert schema.incremental_fields == []

    def test_get_schemas_incremental_endpoints_are_orders_and_attendees(self):
        assert set(INCREMENTAL_ENDPOINTS) == {"orders", "attendees"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events"])

        assert len(schemas) == 1
        assert schemas[0].name == "events"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

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
