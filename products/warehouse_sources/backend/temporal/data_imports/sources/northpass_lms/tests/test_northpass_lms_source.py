from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.northpasslms import (
    NorthpassLMSSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.source import NorthpassLMSSource


class TestNorthpassLMSSource:
    def setup_method(self):
        self.source = NorthpassLMSSource()
        self.team_id = 123
        self.config = NorthpassLMSSourceConfig(api_key="key")

    def test_costly_schemas_are_off_by_default(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        # The event stream re-fetches its full history every sync, and both quiz tables depend on
        # the sent-webhooks log (subscription required, three-month retention) with a per-attempt
        # fan-out, so connecting the source must not silently enable them; everything else keeps
        # syncing by default.
        off_by_default = {schema.name for schema in schemas if not schema.should_sync_default}
        assert off_by_default == {"activity_events", "quiz_attempts", "quiz_attempt_answers"}

    @parameterized.expand(
        [
            ("valid", (True, 200), True, None),
            ("unauthorized", (False, 401), False, "Invalid Northpass API key"),
            ("forbidden", (False, 403), False, "Invalid Northpass API key"),
            (
                "transport_error",
                (False, None),
                False,
                "Could not connect to Northpass. Please check your API key and try again.",
            ),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.source.validate_northpass_credentials"
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
