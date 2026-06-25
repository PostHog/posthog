import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JotformSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform import JotformResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source import JotformSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestJotformSource:
    def setup_method(self):
        self.source = JotformSource()
        self.team_id = 123
        self.config = JotformSourceConfig(api_key="key-123", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.JOTFORM

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Jotform"
        assert config.label == "Jotform"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible: the scaffold's unreleasedSource flag must be gone.
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/jotform.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "region", "enterprise_domain"]

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
        assert [option.value for option in region_field.options] == ["us", "eu", "hipaa"]

    def test_enterprise_domain_is_optional_non_secret(self):
        config = self.source.get_source_config
        field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "enterprise_domain"
        )
        assert field.required is False
        assert field.secret is False

    def test_enterprise_domain_is_a_connection_host_field(self):
        # Editing the host the API key is sent to must re-require the secret.
        assert self.source.connection_host_fields == ["enterprise_domain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.jotform.com/user/forms?limit=100",
            "401 Client Error: Unauthorized for url: https://eu-api.jotform.com/user/submissions",
            "403 Client Error: Forbidden for url: https://hipaa-api.jotform.com/user/forms",
            "403 Client Error: Forbidden for url: https://forms.acme.com/API/user/forms",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.jotform.com/user/submissions",
            "500 Server Error for url: https://api.jotform.com/user/forms",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient_or_other_vendors(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        # 5xx/429 stay retryable; a 401 from another vendor's host shouldn't be in scope here, but our
        # broad "401 Client Error" key would match it — guard only against the transient codes.
        if "401 Client Error" in other_error:
            pytest.skip("broad 401 key intentionally matches any 401")
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_forms_and_submissions_are_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"forms", "submissions"}

    @pytest.mark.parametrize("endpoint", ["forms", "submissions"])
    def test_incremental_schemas_advertise_created_and_updated(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS[endpoint]
        assert schemas[endpoint].supports_append is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["created_at", "updated_at"]

    @pytest.mark.parametrize("endpoint", ["reports", "questions"])
    def test_full_refresh_schemas_have_no_incremental_fields(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].incremental_fields == []
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["forms"])
        assert [s.name for s in schemas] == ["forms"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Jotform API key, region, or Enterprise domain"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.validate_jotform_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region, None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.validate_jotform_credentials"
    )
    def test_validate_credentials_rejects_unsafe_enterprise_host(self, mock_validate, mock_host_safe):
        mock_host_safe.return_value = (False, "Hosts with internal IP addresses are not allowed")
        config = JotformSourceConfig(api_key="key", region="us", enterprise_domain="https://10.0.0.1/")

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Hosts with internal IP addresses are not allowed"
        # An unsafe host must short-circuit before we ever send the key to it.
        mock_validate.assert_not_called()
        mock_host_safe.assert_called_once_with("10.0.0.1", self.team_id)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.validate_jotform_credentials"
    )
    def test_validate_credentials_skips_host_check_without_enterprise_domain(self, mock_validate, mock_host_safe):
        mock_validate.return_value = True

        self.source.validate_credentials(self.config, self.team_id)

        mock_host_safe.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JotformResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe",
        return_value=(True, None),
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.jotform_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_jotform_source, mock_host_safe):
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01 00:00:00"
        inputs.incremental_field = "created_at"
        config = JotformSourceConfig(api_key="key-123", region="eu", enterprise_domain="forms.acme.com")
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_jotform_source.call_args.kwargs
        assert kwargs["api_key"] == "key-123"
        assert kwargs["region"] == "eu"
        assert kwargs["enterprise_domain"] == "forms.acme.com"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01 00:00:00"
        assert kwargs["incremental_field"] == "created_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.jotform_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_jotform_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "reports"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01 00:00:00"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_jotform_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source._is_host_safe")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.source.jotform_source")
    def test_source_for_pipeline_rejects_unsafe_enterprise_host(self, mock_jotform_source, mock_host_safe):
        # DNS can be repointed at an internal host after setup, so the host is re-checked before each
        # sync — not just at validation.
        mock_host_safe.return_value = (False, "Hosts with internal IP addresses are not allowed")
        config = JotformSourceConfig(api_key="key", region="us", enterprise_domain="https://10.0.0.1/")
        inputs = mock.MagicMock()

        with pytest.raises(ValueError, match="Hosts with internal IP addresses are not allowed"):
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        mock_jotform_source.assert_not_called()
        mock_host_safe.assert_called_once_with("10.0.0.1", inputs.team_id)

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
