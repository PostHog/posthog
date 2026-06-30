from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostmarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark import PostmarkResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source import PostmarkSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPostmarkSource:
    def setup_method(self):
        self.source = PostmarkSource()
        self.team_id = 123
        self.config = PostmarkSourceConfig(server_token="test-server-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.POSTMARK

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Postmark"
        assert config.label == "Postmark"
        assert config.releaseStatus == "alpha"
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/postmark.png"
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "server_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert all("api.postmarkapp.com" in key for key in errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["bounces"])

        assert len(schemas) == 1
        assert schemas[0].name == "bounces"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.validate_postmark_credentials"
    )
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.server_token)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.validate_postmark_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Postmark server API token"

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PostmarkResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.postmark_source")
    def test_source_for_pipeline(self, mock_postmark_source):
        mock_postmark_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "messages_outbound"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_postmark_source.assert_called_once_with(
            server_token=self.config.server_token,
            endpoint="messages_outbound",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
