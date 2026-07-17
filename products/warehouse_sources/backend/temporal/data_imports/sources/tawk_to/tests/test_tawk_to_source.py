import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TawkToSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source import TawkToSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to import TawkToResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source"


class TestTawkToSource:
    def setup_method(self):
        self.source = TawkToSource()
        self.team_id = 123
        self.config = TawkToSourceConfig(api_key="api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TAWKTO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "TawkTo"
        assert config.label == "tawk.to"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/tawk_to.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "property_id"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_property_id_field_is_optional(self):
        config = self.source.get_source_config
        property_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "property_id"
        )
        assert property_field.required is False
        assert property_field.secret is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.tawk.to/v1/chat.list",
            "403 Client Error: Forbidden for url: https://api.tawk.to/v1/ticket.list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.tawk.to/v1/chat.list",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # tawk.to's date filters are unverified (API reference is access-gated), so no endpoint
        # may advertise incremental sync until they're confirmed against a live account.
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["chats"])
        assert [schema.name for schema in schemas] == ["chats"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid tawk.to API key"),
        ],
    )
    @mock.patch(f"{MODULE}.validate_tawk_to_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TawkToResumeConfig

    @mock.patch(f"{MODULE}.tawk_to_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tawk_to_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "chats"
        manager = mock.MagicMock()
        config = TawkToSourceConfig(api_key="api-key", property_id="prop-1")

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_tawk_to_source.call_args.kwargs
        assert kwargs["api_key"] == "api-key"
        assert kwargs["property_id"] == "prop-1"
        assert kwargs["endpoint"] == "chats"
        assert kwargs["resumable_source_manager"] is manager

    @pytest.mark.parametrize("raw_property_id", [None, "", "   "])
    @mock.patch(f"{MODULE}.tawk_to_source")
    def test_source_for_pipeline_normalizes_blank_property_id(self, mock_tawk_to_source, raw_property_id):
        inputs = mock.MagicMock()
        inputs.schema_name = "chats"
        config = TawkToSourceConfig(api_key="api-key", property_id=raw_property_id)

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_tawk_to_source.call_args.kwargs["property_id"] is None
