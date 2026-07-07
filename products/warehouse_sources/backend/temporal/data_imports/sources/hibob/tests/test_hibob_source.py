import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HiBobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.source import HiBobSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHiBobSource:
    def setup_method(self):
        self.source = HiBobSource()
        self.team_id = 123
        self.config = HiBobSourceConfig(service_user_id="service-id", service_user_token="service-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HIBOB

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "HiBob"
        assert config.label == "HiBob"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/hibob.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["service_user_id", "service_user_token"]

    def test_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "service_user_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.hibob.com/v1/people/search",
            "403 Client Error: Forbidden for url: https://api.hibob.com/v1/tasks",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.hibob.com/v1/people/search",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # HiBob has no updated-at filters; full refresh only.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["employees"])
        assert len(schemas) == 1
        assert schemas[0].name == "employees"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid HiBob Service User credentials"), False, "Invalid HiBob Service User credentials"),
            ((False, "Connection refused"), False, "Connection refused"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hibob.source.validate_hibob_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("service-id", "service-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.source.hibob_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hibob_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "employees"

        self.source.source_for_pipeline(self.config, inputs)

        mock_hibob_source.assert_called_once()
        kwargs = mock_hibob_source.call_args.kwargs
        assert kwargs["service_user_id"] == "service-id"
        assert kwargs["service_user_token"] == "service-token"
        assert kwargs["endpoint"] == "employees"
