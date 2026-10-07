import pytest
from unittest import mock

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

    def test_get_schemas_incremental_endpoints_are_orders_and_attendees(self):
        assert set(INCREMENTAL_ENDPOINTS) == {"orders", "attendees"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events"])

        assert len(schemas) == 1
        assert schemas[0].name == "events"

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
