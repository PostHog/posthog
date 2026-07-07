import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source import EventeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EventeeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestEventeeSource:
    def setup_method(self):
        self.source = EventeeSource()
        self.team_id = 123
        self.config = EventeeSourceConfig(api_key="tok")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.EVENTEE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Eventee"
        assert config.label == "Eventee"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/eventee.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/eventee"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.eventee.com/public/v1/content",
            "403 Client Error: Forbidden for url: https://api.eventee.com/public/v1/groups",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.eventee.com/public/v1/reviews",
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
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "reviews"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # Static catalog with no I/O — required for the public docs Supported tables section to render.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Eventee API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source.validate_eventee_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("tok")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source.eventee_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_eventee_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"

        self.source.source_for_pipeline(self.config, inputs)

        mock_eventee_source.assert_called_once()
        kwargs = mock_eventee_source.call_args.kwargs
        assert kwargs["api_key"] == "tok"
        assert kwargs["endpoint"] == "reviews"
