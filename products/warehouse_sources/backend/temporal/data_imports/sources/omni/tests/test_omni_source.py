import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omni import OmniSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.source import OmniSource


class TestOmniSource:
    def setup_method(self):
        self.source = OmniSource()
        self.team_id = 123
        self.config = OmniSourceConfig(host="https://acme.omniapp.co", api_key="omni-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.omniapp.co/api/v1/whoami",
            "403 Client Error: Forbidden for url: https://acme.omniapp.co/api/v1/documents",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_unrelated_server_error(self):
        # Omni's host is customer-controlled (no fixed domain to anchor on), so the auth-failure
        # keys are necessarily generic status-line substrings — this only guards against a key so
        # broad it would also swallow a transient 5xx.
        non_retryable_errors = self.source.get_non_retryable_errors()
        other_error = "500 Server Error for url: https://acme.omniapp.co/api/v1/documents"
        assert not any(key in other_error for key in non_retryable_errors)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.omni.source.get_omni_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates(self, mock_get_permissions):
        mock_get_permissions.return_value = {"Users": "some reason", "Documents": None}

        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["Users", "Documents"])

        assert result == {"Users": "some reason", "Documents": None}
        mock_get_permissions.assert_called_once_with(self.config.host, self.config.api_key, ["Users", "Documents"])
