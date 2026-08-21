import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer import (
    AppsFlyerCredentialsError,
    AppsFlyerRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source import AppsFlyerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsflyer import (
    AppsFlyerSourceConfig,
)


class TestAppsFlyerSource:
    def setup_method(self):
        self.source = AppsFlyerSource()
        self.team_id = 123
        self.config = AppsFlyerSourceConfig(app_id="id123", api_token="token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source.validate_appsflyer_credentials"
    )
    def test_validate_credentials_succeeds(self, mock_validate):
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("token", "id123")

    @pytest.mark.parametrize(
        "raised",
        [AppsFlyerRetryableError("status=429"), requests.ConnectionError(), requests.ReadTimeout()],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source.validate_appsflyer_credentials"
    )
    def test_validate_credentials_reports_transient_failures_distinctly(self, mock_validate, raised):
        mock_validate.side_effect = raised

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "temporary" in error_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source.validate_appsflyer_credentials"
    )
    def test_validate_credentials_surfaces_specific_rejection_message(self, mock_validate):
        # A rejected token/app id raises AppsFlyerCredentialsError; its message reaches the user
        # verbatim instead of the conflated "Invalid AppsFlyer API token or app id".
        mock_validate.side_effect = AppsFlyerCredentialsError("AppsFlyer rejected the API token.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "AppsFlyer rejected the API token."
