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

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.northpass.com/v2/people?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.northpass.com/v2/courses?limit=100"),
            (
                "empty_quiz_log",
                "Northpass sent-webhooks log returned no quiz-completed events, so quiz_attempts has no rows to sync",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("throttle", "429 Client Error: Too Many Requests for url: https://api.northpass.com/v2/people"),
            ("server", "500 Server Error: Internal Server Error for url: https://api.northpass.com/v2/people"),
            ("timeout", "HTTPSConnectionPool(host='api.northpass.com', port=443): Read timed out."),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, _name, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["courses"])
        assert len(schemas) == 1
        assert schemas[0].name == "courses"

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
