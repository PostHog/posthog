import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    Script,
    ScriptedResponse,
    always,
    scripted_network,
)
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
            ("valid", 200, True, None),
            ("unauthorized", 401, False, "Invalid Northpass API key"),
            ("forbidden", 403, False, "Invalid Northpass API key"),
            (
                "transport_error",
                None,
                False,
                "Could not connect to Northpass. Please check your API key and try again.",
            ),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        script: Script = (
            [ScriptedResponse(status=status)] if status is not None else always(requests.ConnectionError("reset"))
        )
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log
        assert {request.url for request in network.requests_log} == {"https://api.northpass.com/v2/courses?limit=1"}
        assert all(request.headers["x-api-key"] == "key" for request in network.requests_log)
        assert network.session_options == [{"redact_values": ("key",), "allow_redirects": False}]
