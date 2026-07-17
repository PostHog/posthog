import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PandaDocSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc import PandaDocResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source import PandaDocSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPandaDocSource:
    def setup_method(self):
        self.source = PandaDocSource()
        self.team_id = 123
        self.config = PandaDocSourceConfig(api_key="api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PANDADOC

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "PandaDoc"
        assert config.label == "PandaDoc"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/pandadoc.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.pandadoc.com/public/v1/documents",
            "403 Client Error: Forbidden for url: https://api.pandadoc.com/public/v1/members",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.pandadoc.com/public/v1/documents",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only documents expose server-side date filters (modified_from/created_from).
        assert incremental == {"documents"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["documents"].incremental_fields == INCREMENTAL_FIELDS["documents"]
        assert schemas["templates"].incremental_fields == []
        assert schemas["templates"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["documents"])
        assert len(schemas) == 1
        assert schemas[0].name == "documents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid PandaDoc API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source.validate_pandadoc_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PandaDocResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source.pandadoc_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pandadoc_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "documents"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000000Z"
        inputs.incremental_field = "date_modified"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pandadoc_source.assert_called_once()
        kwargs = mock_pandadoc_source.call_args.kwargs
        assert kwargs["api_key"] == "api-key"
        assert kwargs["endpoint"] == "documents"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000000Z"
        assert kwargs["incremental_field"] == "date_modified"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source.pandadoc_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_pandadoc_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "templates"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000000Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_pandadoc_source.call_args.kwargs["db_incremental_field_last_value"] is None
