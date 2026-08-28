import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer import (
    AppsFlyerCredentialsError,
    AppsFlyerRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source import AppsFlyerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsflyer import (
    AppsFlyerSourceConfig,
)


class TestAppsFlyerSource:
    def setup_method(self):
        self.source = AppsFlyerSource()
        self.team_id = 123
        self.config = AppsFlyerSourceConfig(app_id="id123", api_token="token")

    def test_connection_host_fields_includes_app_id(self):
        # Changing app_id retargets the stored token, so editing it must require re-entering secrets.
        assert self.source.connection_host_fields == ["app_id"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://hq1.appsflyer.com/api/agg-data/export/app/id123/daily_report/v5",
            "403 Client Error: Forbidden for url: https://hq1.appsflyer.com/api/agg-data/export/app/id123/geo_by_date_report/v5",
            "404 Client Error: Not Found for url: https://hq1.appsflyer.com/api/agg-data/export/app/nope/daily_report/v5",
            "416 Client Error: Requested Range Not Satisfiable for url: https://hq1.appsflyer.com/api/agg-data/export/app/id123/geo_by_date_report/v5?from=2024-01-01&to=2024-01-05",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://hq1.appsflyer.com/api/agg-data/export/app/id123/daily_report/v5",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every aggregate report takes a server-side from/to date window.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

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
