import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.braze import BrazeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.source import BrazeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrazeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

BASE_URL = "https://rest.iad-01.braze.com"


class TestBrazeSource:
    def setup_method(self):
        self.source = BrazeSource()
        self.team_id = 123
        self.config = BrazeSourceConfig(api_key="key", url=BASE_URL)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BRAZE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Braze"
        assert config.label == "Braze"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/braze.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "url"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_url_field_is_required_text(self):
        config = self.source.get_source_config
        url_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "url")
        assert url_field.type == SourceFieldInputConfigType.TEXT
        assert url_field.required is True
        assert url_field.secret is False

    def test_url_is_a_connection_host_field(self):
        # The API key is sent to the host in `url`, so retargeting it must re-require the secret.
        assert self.source.connection_host_fields == ["url"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://rest.iad-01.braze.com/campaigns/list?page=0",
            "403 Client Error: Forbidden for url: https://rest.iad-01.braze.com/events/list?page=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://rest.iad-01.braze.com/campaigns/list",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only templates/content blocks expose Braze's server-side `modified_after` filter.
        assert incremental == {"email_templates", "content_blocks"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["email_templates"].incremental_fields == INCREMENTAL_FIELDS["email_templates"]
        assert schemas["content_blocks"].incremental_fields == INCREMENTAL_FIELDS["content_blocks"]
        assert schemas["campaigns"].incremental_fields == []
        assert schemas["campaigns"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "campaigns"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Braze API key"), False, "Invalid Braze API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.url, "/campaigns/list", self.team_id)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_probes_schema_specific_path(self, mock_validate):
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, schema_name="email_templates")

        mock_validate.assert_called_once_with(
            self.config.api_key, self.config.url, "/templates/email/list", self.team_id
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_rejects_unknown_schema(self, mock_validate):
        is_valid, error_message = self.source.validate_credentials(
            self.config, self.team_id, schema_name="does_not_exist"
        )

        assert is_valid is False
        assert "does_not_exist" in (error_message or "")
        # Never probes the API for an unknown schema.
        mock_validate.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_accepts_missing_scope_at_source_create(self, mock_validate):
        # A scoped key may lack the probe endpoint's permission at create time — accepted.
        mock_validate.return_value = (False, "Your Braze API key does not have permission for this endpoint")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_enforces_scope_for_specific_schema(self, mock_validate):
        mock_validate.return_value = (False, "Your Braze API key does not have permission for this endpoint")

        is_valid, error_message = self.source.validate_credentials(
            self.config, self.team_id, schema_name="email_templates"
        )

        assert is_valid is False
        assert error_message == "Your Braze API key does not have permission for this endpoint"

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BrazeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.braze_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_braze_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "email_templates"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updated_at"
        inputs.team_id = 777
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_braze_source.assert_called_once()
        kwargs = mock_braze_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["base_url"] == BASE_URL
        assert kwargs["endpoint"] == "email_templates"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 777
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.braze_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_braze_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_braze_source.call_args.kwargs["db_incremental_field_last_value"] is None
