import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai import (
    AssemblyAIResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.source import AssemblyAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AssemblyAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAssemblyAISource:
    def setup_method(self):
        self.source = AssemblyAISource()
        self.team_id = 123
        self.config = AssemblyAISourceConfig(api_key="key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ASSEMBLYAI

    def test_connection_host_fields_includes_region(self):
        # `region` selects the host the stored API key is sent to, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["region"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "AssemblyAI"
        assert config.label == "AssemblyAI"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/assemblyai.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/assemblyai"

    def test_source_config_fields(self):
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["api_key", "region"]

        api_key = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True

        region = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert {opt.value for opt in region.options} == {"us", "eu"}
        assert region.defaultValue == "us"

    def test_lists_tables_without_credentials(self):
        # get_schemas iterates a static endpoint catalog with no I/O, so the public docs catalog renders.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert [t["name"] for t in documented] == ["transcripts"]
        assert documented[0]["sync_methods"] == ["Full refresh"]

    def test_get_schemas_is_full_refresh_only(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        transcripts = schemas["transcripts"]
        # AssemblyAI exposes no server-side `created >= X` filter, so we never advertise incremental.
        assert transcripts.supports_incremental is False
        assert transcripts.supports_append is False
        assert transcripts.incremental_fields == INCREMENTAL_FIELDS["transcripts"]

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["transcripts"])] == [
            "transcripts"
        ]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.assemblyai.com/v2/transcript?limit=200",
            "401 Client Error: Unauthorized for url: https://api.eu.assemblyai.com/v2/transcript/abc",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.assemblyai.com/v2/transcript",
            "429 Client Error: Too Many Requests for url: https://api.assemblyai.com/v2/transcript",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_or_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AssemblyAI API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.source.validate_assemblyai_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AssemblyAIResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.source.assemblyai_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_assemblyai_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "transcripts"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_assemblyai_source.assert_called_once()
        kwargs = mock_assemblyai_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "transcripts"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_keyed_by_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "transcripts" in descriptions
