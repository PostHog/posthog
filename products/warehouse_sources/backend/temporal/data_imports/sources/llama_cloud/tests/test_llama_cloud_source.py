from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LlamaCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.llama_cloud import (
    LlamaCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.settings import (
    ENDPOINTS,
    LLAMA_CLOUD_ENDPOINTS,
    LlamaCloudEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source import LlamaCloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(
    schema_name: str = "parse_jobs",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestLlamaCloudSource:
    def setup_method(self) -> None:
        self.source = LlamaCloudSource()
        self.team_id = 1
        self.config = LlamaCloudSourceConfig(api_key="llx-test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LLAMACLOUD

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "LlamaCloud"
        assert config.label == "LlamaCloud"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/llama_cloud.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/llama-cloud"

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig))
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

        region_field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert region_field.name == "region"
        assert region_field.defaultValue == "na"
        assert [option.value for option in region_field.options] == ["na", "eu"]

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("parse_jobs", True, "created_at"),
            ("extract_jobs", True, "created_at"),
            ("classify_jobs", True, "created_at"),
            ("batches", True, "created_at"),
            ("split_jobs", True, "created_at"),
            ("sheets_jobs", True, "created_at"),
            ("usage_metrics", True, "day"),
            # No server-side timestamp filter on these listings, so full refresh only.
            ("projects", False, None),
            ("pipelines", False, None),
            ("files", False, None),
        ]
    )
    def test_get_schemas_incremental_semantics(
        self, endpoint: str, supports_incremental: bool, incremental_field: str | None
    ) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        assert [f["field"] for f in schema.incremental_fields] == ([incremental_field] if incremental_field else [])

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["parse_jobs", "projects"])
        assert {s.name for s in schemas} == {"parse_jobs", "projects"}

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_job_schemas_declare_status_lookback(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["parse_jobs"].default_incremental_lookback_seconds == 24 * 60 * 60
        assert schemas["projects"].default_incremental_lookback_seconds is None

    def test_http_sample_capture_is_fail_closed(self) -> None:
        # A new endpoint config must default to no HTTP sample capture; only endpoints whose
        # response is limited to safe metadata opt in. Guards against a job/config endpoint
        # (which can carry customer document content or embedded credentials) silently
        # sampling raw responses into object storage.
        assert LlamaCloudEndpointConfig(name="x", path="/y").capture_http_samples is False
        capturing = {name for name, config in LLAMA_CLOUD_ENDPOINTS.items() if config.capture_http_samples}
        assert capturing == {"projects", "usage_metrics"}

    def test_documented_tables_render_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        parse_jobs = next(t for t in tables if t["name"] == "parse_jobs")
        assert parse_jobs["description"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.cloud.llamaindex.ai/api/v2/parse?page_size=100",),
            ("401 Client Error: Unauthorized for url: https://api.cloud.eu.llamaindex.ai/api/v2/projects",),
            ("403 Client Error: Forbidden for url: https://api.cloud.llamaindex.ai/api/v1/beta/files",),
            # The beta usage-metrics endpoint 400s for organizations it isn't available to; the
            # request is otherwise valid, so retrying can't help. Both regional hosts must match.
            (
                "400 Client Error: Bad Request for url: https://api.cloud.llamaindex.ai/api/v1/beta/usage-metrics?page_size=100&organization_id=00000000-0000-0000-0000-000000000000",
            ),
            (
                "400 Client Error: Bad Request for url: https://api.cloud.eu.llamaindex.ai/api/v1/beta/usage-metrics?page_size=100&organization_id=00000000-0000-0000-0000-000000000000",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.cloud.llamaindex.ai/api/v2/parse",),
            ("401 Client Error: Unauthorized for url: https://api.example.com/api/v2/parse",),
            # A 400 on a different endpoint may be a fixable bug in our request, so it must stay
            # retryable and keep surfacing rather than being swallowed by the usage-metrics key.
            ("400 Client Error: Bad Request for url: https://api.cloud.llamaindex.ai/api/v2/parse?page_size=100",),
        ]
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source.validate_llama_cloud_credentials"
    )
    def test_validate_credentials_passes_region(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = LlamaCloudSourceConfig(api_key="llx-test", region="eu")

        result = self.source.validate_credentials(config, self.team_id)

        assert result == (True, None)
        mock_validate.assert_called_once_with(api_key="llx-test", region="eu")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert manager._data_class is LlamaCloudResumeConfig

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source.llama_cloud_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="extract_jobs",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        manager = MagicMock()
        config = LlamaCloudSourceConfig(api_key="llx-test", region="eu")

        self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="llx-test",
            region="eu",
            endpoint="extract_jobs",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source.llama_cloud_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="parse_jobs",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
