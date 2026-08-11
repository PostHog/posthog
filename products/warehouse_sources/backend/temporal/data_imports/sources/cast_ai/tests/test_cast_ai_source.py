from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai import CastAiResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.source import CastAiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.castai import CastAiSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCastAiSource:
    def setup_method(self) -> None:
        self.source = CastAiSource()
        self.team_id = 123
        self.config = CastAiSourceConfig(api_key="castai-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CASTAI

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "CastAi"
        assert config.label == "CAST AI"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/cast_ai.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cast-ai"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # No server-side timestamp filter is documented for listing clusters, so it stays
        # full refresh.
        assert schemas["clusters"].supports_incremental is False
        assert schemas["clusters"].incremental_fields == []

        for name, field_name in (("cluster_cost_reports", "timestamp"), ("cluster_savings_history", "createdAt")):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == [field_name]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["clusters"])
        assert len(schemas) == 1
        assert schemas[0].name == "clusters"

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.cast.ai/v1/kubernetes/external-clusters",
            "403 Client Error: Forbidden for url: https://api.cast.ai/v1/kubernetes/external-clusters",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.cast.ai/v1/kubernetes/external-clusters"
            for key in non_retryable
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.source.validate_castai_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="cluster_cost_reports")

        assert result == (True, None)
        mock_validate.assert_called_once_with("castai-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CastAiResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.source.cast_ai_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cast_ai_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "cluster_cost_reports"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "timestamp"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_cast_ai_source.call_args.kwargs
        assert kwargs["api_key"] == "castai-key"
        assert kwargs["endpoint"] == "cluster_cost_reports"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "timestamp"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.source.cast_ai_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_cast_ai_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "cluster_cost_reports"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_cast_ai_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
