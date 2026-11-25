import pytest
from unittest import mock

import requests

from products.warehouse_sources.sources.appsflyer._config import AppsFlyerSourceConfig
from products.warehouse_sources.sources.appsflyer.appsflyer import AppsFlyerCredentialsError, AppsFlyerRetryableError
from products.warehouse_sources.sources.appsflyer.source import AppsFlyerSource


class TestAppsFlyerSource:
    def setup_method(self):
        self.source = AppsFlyerSource()
        self.team_id = 123
        self.config = AppsFlyerSourceConfig(app_id="id123", api_token="token")

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("daily_report", True),
            ("geo_report", True),
            ("partners_report", True),
            ("installs", False),
            ("installs_organic", False),
            ("installs_retargeting", False),
            ("in_app_events", False),
            ("in_app_events_organic", False),
            ("in_app_events_retargeting", False),
            ("uninstall_events", False),
            ("ad_revenue", False),
            ("ad_revenue_organic", False),
            ("ad_revenue_retargeting", False),
            ("blocked_installs", False),
            ("blocked_in_app_events", False),
            ("post_attribution_installs", False),
            ("master_report", False),
            ("reinstalls", False),
            ("reinstalls_organic", False),
            ("install_postbacks", False),
            ("in_app_event_postbacks", False),
            ("retargeting_install_postbacks", False),
            ("retargeting_in_app_event_postbacks", False),
            ("skan_performance_report", False),
        ],
    )
    def test_only_aggregate_reports_sync_by_default(self, name, expected):
        # Raw data, the Master API and Protect360 need AppsFlyer packages most accounts lack.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[name].should_sync_default is expected

    def test_connection_host_fields_includes_app_id(self):
        # Changing app_id retargets the stored token, so editing it must require re-entering secrets.
        assert self.source.connection_host_fields == ["app_id"]

    @mock.patch("products.warehouse_sources.sources.appsflyer.source.validate_appsflyer_credentials")
    def test_validate_credentials_succeeds(self, mock_validate):
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("token", "id123")

    @pytest.mark.parametrize(
        "raised",
        [AppsFlyerRetryableError("status=429"), requests.ReadTimeout()],
    )
    @mock.patch("products.warehouse_sources.sources.appsflyer.source.validate_appsflyer_credentials")
    def test_validate_credentials_reports_transient_failures_distinctly(self, mock_validate, raised):
        mock_validate.side_effect = raised

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "temporary" in error_message

    @mock.patch("products.warehouse_sources.sources.appsflyer.source.validate_appsflyer_credentials")
    def test_validate_credentials_surfaces_specific_rejection_message(self, mock_validate):
        # A rejected token/app id raises AppsFlyerCredentialsError; its message reaches the user
        # verbatim instead of the conflated "Invalid AppsFlyer API token or app id".
        mock_validate.side_effect = AppsFlyerCredentialsError("AppsFlyer rejected the API token.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "AppsFlyer rejected the API token."
