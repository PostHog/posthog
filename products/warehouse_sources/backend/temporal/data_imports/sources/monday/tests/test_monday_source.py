import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.monday import MondaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.monday import (
    MONDAY_VERSION_2026_07,
    MONDAY_VERSION_2026_10,
    MONDAY_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.source import MondaySource


class TestMondaySource:
    def setup_method(self):
        self.source = MondaySource()
        self.team_id = 123
        self.config = MondaySourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "monday.com API error (retryable): status=500",
            "monday.com internal server error (retryable): Internal Server Error; Internal server error",
        ],
    )
    def test_retryable_errors_match_transient_monday_errors(self, observed_error):
        retryable_errors = self.source.get_retryable_errors()
        assert error_message_matches(observed_error, retryable_errors)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "monday.com GraphQL error: Not authenticated",
            "monday.com GraphQL error: User unauthorized",
        ],
    )
    def test_non_retryable_errors_match_auth_and_permission_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert error_message_matches(observed_error, non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message, api_version, expected_api_version",
        [
            (True, True, None, None, MONDAY_VERSION_2026_10),
            (True, True, None, MONDAY_VERSION_V2, MONDAY_VERSION_V2),
            (True, True, None, MONDAY_VERSION_2026_07, MONDAY_VERSION_2026_07),
            (False, False, "Invalid monday.com API token", None, MONDAY_VERSION_2026_10),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.monday.source.validate_monday_credentials"
    )
    def test_validate_credentials(
        self, mock_validate, mock_return, expected_valid, expected_message, api_version, expected_api_version
    ):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, api_version=api_version)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token, expected_api_version)

    @pytest.mark.parametrize(
        "pinned_version, expected_header",
        [
            (MONDAY_VERSION_V2, "2024-10"),
            (MONDAY_VERSION_2026_07, "2026-07"),
            (MONDAY_VERSION_2026_10, "2026-10"),
            (None, "2026-10"),
        ],
    )
    def test_sync_sends_the_source_pin(self, pinned_version: str | None, expected_header: str) -> None:
        result = SourceDriver(self.source, self.config).run(
            "users",
            [ScriptedResponse(json={"data": {"users": []}})],
            api_version=pinned_version,
        )

        assert result.raised is None
        assert result.session_options[0]["headers"]["API-Version"] == expected_header
        assert result.requests[0].headers["api-version"] == expected_header
