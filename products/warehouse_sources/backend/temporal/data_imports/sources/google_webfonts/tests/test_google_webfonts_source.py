import pytest
from unittest import mock

import requests

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleWebfontsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source import GoogleWebfontsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source"


class TestGoogleWebfontsSource:
    def setup_method(self):
        self.source = GoogleWebfontsSource()
        self.team_id = 123
        self.config = GoogleWebfontsSourceConfig(api_key="AIza-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GOOGLEWEBFONTS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "GoogleWebfonts"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/google-webfonts"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://www.googleapis.com/webfonts/v1/webfonts?sort=alpha",
            "403 Client Error: Forbidden for url: https://www.googleapis.com/webfonts/v1/webfonts?sort=alpha",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # A 400 from an unrelated API must not trip the Google Webfonts credential handler.
            "400 Client Error: Bad Request for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://www.googleapis.com/webfonts/v1/webfonts",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["webfonts"])
        assert len(schemas) == 1
        assert schemas[0].name == "webfonts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self):
        # Static catalog opt-in powers the posthog.com "Supported tables" section.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        webfonts = next(t for t in tables if t["name"] == "webfonts")
        assert webfonts["sync_methods"] == ["Full refresh"]
        assert webfonts["description"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Google API key"),
        ],
    )
    @mock.patch(f"{_MODULE}.validate_google_webfonts_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("AIza-key")

    @mock.patch(f"{_MODULE}.validate_google_webfonts_credentials")
    def test_validate_credentials_reports_connection_failure_distinctly(self, mock_validate):
        # A transient network failure must not be reported as an invalid key, or the user
        # wastes time recreating a working credential.
        mock_validate.side_effect = requests.ConnectionError("boom")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Could not reach the Google Fonts API. Check your network connection and try again."

    @mock.patch(f"{_MODULE}.google_webfonts_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "webfonts"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "AIza-key"
        assert kwargs["endpoint"] == "webfonts"
