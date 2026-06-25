import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailgunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun import MailgunResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source import MailgunSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestMailgunSource:
    def setup_method(self):
        self.source = MailgunSource()
        self.team_id = 123
        self.config = MailgunSourceConfig(api_key="key-123", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.MAILGUN

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Mailgun"
        assert config.label == "Mailgun"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/mailgun.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "region"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_region_field_is_select_with_us_default(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert region_field.required is True
        assert region_field.defaultValue == "us"
        assert [option.value for option in region_field.options] == ["us", "eu"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.mailgun.net/v3/example.com/events?limit=300",
            "401 Client Error: Unauthorized for url: https://api.eu.mailgun.net/v4/domains?limit=1000",
            "403 Client Error: Forbidden for url: https://api.mailgun.net/v3/example.com/bounces",
            "403 Client Error: Forbidden for url: https://api.eu.mailgun.net/v3/lists/pages",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.mailgun.net/v3/example.com/events",
            "429 Client Error: Too Many Requests for url: https://api.mailgun.net/v3/example.com/events",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the Events API exposes a server-side timestamp filter.
        assert incremental == {"events"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["events"].incremental_fields == INCREMENTAL_FIELDS["events"]
        assert schemas["events"].supports_append is True

    @pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e != "events"])
    def test_full_refresh_schemas_have_no_incremental_fields(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].incremental_fields == []
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events"])
        assert len(schemas) == 1
        assert schemas[0].name == "events"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Mailgun API key or region"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source.validate_mailgun_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MailgunResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source.mailgun_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_mailgun_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "timestamp"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_mailgun_source.assert_called_once()
        kwargs = mock_mailgun_source.call_args.kwargs
        assert kwargs["api_key"] == "key-123"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "timestamp"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source.mailgun_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_mailgun_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "bounces"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_mailgun_source.call_args.kwargs["db_incremental_field_last_value"] is None
