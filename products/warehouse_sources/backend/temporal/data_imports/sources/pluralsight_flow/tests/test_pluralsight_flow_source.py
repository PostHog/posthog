import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pluralsightflow import (
    PluralsightFlowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source import (
    PluralsightFlowSource,
)


class TestPluralsightFlowSource:
    def setup_method(self):
        self.source = PluralsightFlowSource()
        self.team_id = 123
        self.config = PluralsightFlowSourceConfig(workspace="acme", api_key="key")

    def test_workspace_listed_as_connection_host_field(self):
        # The API key is sent to <workspace>.appfireflow.com, so retargeting the workspace must
        # re-require it.
        assert self.source.connection_host_fields == ["workspace"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.appfireflow.com/v3/customer/core/users/",
            "403 Client Error: Forbidden for url: https://api.appfireflow.com/collaboration/code/metrics/",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.appfireflow.com/v3/customer/core/users/",
            "500 Server Error: Internal Server Error for url: https://acme.appfireflow.com/v3/customer/core/users/",
            "HTTPSConnectionPool(host='acme.appfireflow.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Your Flow API key is invalid or expired."),
            ((False, 403), False, "Invalid credentials"),
            ((False, None), False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source"
        ".validate_pluralsight_flow_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key", "acme")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source"
        ".validate_pluralsight_flow_credentials"
    )
    def test_validate_credentials_surfaces_bad_workspace(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Flow workspace: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Flow workspace" in (error_message or "")
