import pytest
from unittest import mock

import requests

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.appsflyer import (
    AppsFlyerCredentialsError,
    AppsFlyerRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source import AppsFlyerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppsFlyerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAppsFlyerSource:
    def setup_method(self):
        self.source = AppsFlyerSource()
        self.team_id = 123
        self.config = AppsFlyerSourceConfig(app_id="id123", api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.APPSFLYER

    def test_connection_host_fields_includes_app_id(self):
        # Changing app_id retargets the stored token, so editing it must require re-entering secrets.
        assert self.source.connection_host_fields == ["app_id"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "AppsFlyer"
        assert config.label == "AppsFlyer"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/appsflyer.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["app_id", "api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

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

    def test_schemas_advertise_date_cursor(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["daily_report"].incremental_fields == INCREMENTAL_FIELDS["daily_report"]
        assert [f["field"] for f in schemas["daily_report"].incremental_fields] == ["date"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["daily_report"])
        assert len(schemas) == 1
        assert schemas[0].name == "daily_report"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source.appsflyer_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_af_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "daily_report"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01"

        self.source.source_for_pipeline(self.config, inputs)

        mock_af_source.assert_called_once()
        kwargs = mock_af_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["app_id"] == "id123"
        assert kwargs["endpoint"] == "daily_report"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.source.appsflyer_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_af_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "daily_report"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01"

        self.source.source_for_pipeline(self.config, inputs)

        assert mock_af_source.call_args.kwargs["db_incremental_field_last_value"] is None
