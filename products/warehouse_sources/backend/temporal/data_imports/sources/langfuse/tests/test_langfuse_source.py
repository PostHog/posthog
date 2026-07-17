import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.langfuse import (
    DEEP_PAGINATION_ERROR,
    RESPONSE_LIMIT_ERROR,
    REWINDOW_STUCK_ERROR,
    LangfuseResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLangfuseSource:
    def setup_method(self):
        self.source = LangfuseSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.host = "https://cloud.langfuse.com"
        self.config.public_key = "pk-lf-key"
        self.config.secret_key = "sk-lf-key"

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LANGFUSE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Langfuse"
        assert config.label == "Langfuse"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/langfuse.svg"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "public_key", "secret_key"]

        host_field, public_key_field, secret_key_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.required is False
        assert host_field.secret is False

        assert isinstance(public_key_field, SourceFieldInputConfig)
        assert public_key_field.required is True
        assert public_key_field.secret is False

        # The secret key must stay a secret password field: the serializer derives which config
        # keys are sensitive from these flags.
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.secret is True
        assert secret_key_field.required is True

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error", "403 Client Error", RESPONSE_LIMIT_ERROR, DEEP_PAGINATION_ERROR, REWINDOW_STUCK_ERROR],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("traces", True),
            ("observations", True),
            ("scores", True),
            ("sessions", True),
            ("prompts", True),
            ("datasets", False),
            ("dataset_items", False),
            ("models", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["traces"])
        assert len(schemas) == 1
        assert schemas[0].name == "traces"

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Langfuse API keys"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.validate_langfuse_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="traces")

        assert result == mock_return
        mock_validate.assert_called_once_with(
            self.config.host, self.config.public_key, self.config.secret_key, self.team_id
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LangfuseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.langfuse_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_langfuse_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "traces"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "timestamp"

        manager = mock.MagicMock()
        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_langfuse_source.call_args.kwargs
        assert kwargs["host"] == "https://cloud.langfuse.com"
        assert kwargs["public_key"] == "pk-lf-key"
        assert kwargs["secret_key"] == "sk-lf-key"
        assert kwargs["endpoint"] == "traces"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "timestamp"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.langfuse_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_langfuse_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "datasets"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_langfuse_source.call_args.kwargs["db_incremental_field_last_value"] is None
