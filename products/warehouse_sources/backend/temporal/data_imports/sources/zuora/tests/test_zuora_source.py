import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZuoraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ZUORA_ENVIRONMENT_HOSTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source import ZuoraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.zuora import ZuoraResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestZuoraSource:
    def setup_method(self):
        self.source = ZuoraSource()
        self.team_id = 123
        self.config = ZuoraSourceConfig(environment="us_production", client_id="cid", client_secret="sec")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ZUORA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Zuora"
        assert config.label == "Zuora"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/zuora.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["environment", "client_id", "client_secret"]

    def test_environment_field_covers_all_hosts(self):
        config = self.source.get_source_config
        env_field = next(f for f in config.fields if f.name == "environment")
        assert isinstance(env_field, SourceFieldSelectConfig)
        assert env_field.defaultValue == "us_production"
        assert {option.value for option in env_field.options} == set(ZUORA_ENVIRONMENT_HOSTS.keys())

    def test_client_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://rest.zuora.com/oauth/token",
            "401 Client Error: Unauthorized for url: https://rest.sandbox.eu.zuora.com/oauth/token",
            "403 Client Error: Forbidden for url: https://rest.zuora.com/object-query/accounts",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://rest.zuora.com/object-query/accounts"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every Object Query object filters server-side on updateddate.
        assert all(schema.supports_incremental for schema in schemas)
        assert all([f["field"] for f in schema.incremental_fields] == ["updatedDate"] for schema in schemas)
        assert {schema.name: schema.incremental_fields for schema in schemas} == INCREMENTAL_FIELDS

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invoices"])
        assert len(schemas) == 1
        assert schemas[0].name == "invoices"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source.validate_zuora_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "Invalid Zuora credentials" in (error_message or "")
        mock_validate.assert_called_once_with("us_production", "cid", "sec")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZuoraResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source.zuora_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_zuora_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zuora_source.assert_called_once()
        kwargs = mock_zuora_source.call_args.kwargs
        assert kwargs["environment"] == "us_production"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source.zuora_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_zuora_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_zuora_source.call_args.kwargs["db_incremental_field_last_value"] is None
