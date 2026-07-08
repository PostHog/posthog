from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailjetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet import MailjetResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source import MailJetSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_STATISTICS_ENDPOINTS = {"openinformation", "clickstatistics"}


class TestMailJetSource:
    def setup_method(self):
        self.source = MailJetSource()
        self.team_id = 123
        self.config = MailjetSourceConfig(api_key="key", secret_key="secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.MAILJET

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Mailjet"
        assert config.label == "Mailjet"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/mailjet.png"

        assert {f.name for f in config.fields} == {"api_key", "secret_key"}
        for field in config.fields:
            assert isinstance(field, SourceFieldInputConfig)
            assert field.type == SourceFieldInputConfigType.PASSWORD
            assert field.secret is True
            assert field.required is True

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            expected_incremental = schema.name in _STATISTICS_ENDPOINTS
            assert schema.supports_incremental is expected_incremental
            assert schema.supports_append is expected_incremental
            if expected_incremental:
                assert len(schema.incremental_fields) == 1
            else:
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contact"])

        assert len(schemas) == 1
        assert schemas[0].name == "contact"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.validate_mailjet_credentials"
    )
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.api_key, self.config.secret_key)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.validate_mailjet_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate):
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Mailjet API key or secret key"

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MailjetResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source.mailjet_source")
    def test_source_for_pipeline(self, mock_mailjet_source):
        mock_mailjet_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "contact"
        inputs.should_use_incremental_field = False
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_mailjet_source.assert_called_once_with(
            api_key=self.config.api_key,
            secret_key=self.config.secret_key,
            endpoint="contact",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
