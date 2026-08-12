from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.scale_ai import ScaleAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.source import ScaleAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestScaleAISourceConfig:
    def test_source_type(self) -> None:
        assert ScaleAISource().source_type == ExternalDataSourceType.SCALEAI

    def test_config_identity_and_release(self) -> None:
        config = ScaleAISource().get_source_config
        assert config.name == SchemaExternalDataSourceType.SCALE_AI
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_config_requires_a_secret_api_key_field(self) -> None:
        # A non-secret or non-required key field would leak the credential or let the form submit blank.
        fields = ScaleAISource().get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_docs_url_matches_slug(self) -> None:
        assert ScaleAISource().get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/scale-ai"


class TestScaleAISchemas:
    def test_lists_all_endpoints(self) -> None:
        schemas = ScaleAISource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == {"tasks", "batches", "projects"}

    @parameterized.expand(
        [
            ("tasks", True, ["task_id"], ["updated_at", "created_at"]),
            ("batches", True, ["name"], ["created_at"]),
            ("projects", False, ["name"], []),
        ]
    )
    def test_schema_incremental_and_keys(
        self, name: str, incremental: bool, primary_keys: list[str], incremental_fields: list[str]
    ) -> None:
        schemas = {s.name: s for s in ScaleAISource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[name]
        assert schema.supports_incremental is incremental
        assert schema.detected_primary_keys == primary_keys
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields

    def test_names_filter(self) -> None:
        schemas = ScaleAISource().get_schemas(MagicMock(), team_id=1, names=["tasks"])
        assert [s.name for s in schemas] == ["tasks"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # The docs Supported-tables section depends on this static, no-I/O catalog being exposed.
        tables = ScaleAISource().get_documented_tables()
        assert {t["name"] for t in tables} == {"tasks", "batches", "projects"}
        tasks = next(t for t in tables if t["name"] == "tasks")
        assert tasks["primary_keys"] == ["task_id"]
        assert tasks["description"]  # canonical description flows through


class TestScaleAICredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Scale AI API key"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        config = MagicMock(api_key="live_key")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.source.validate_scale_ai_credentials",
            return_value=probe_result,
        ):
            assert ScaleAISource().validate_credentials(config, team_id=1) == expected

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.scale.com/v1/tasks?limit=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.scale.com/v1/batches?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = ScaleAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.scale.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.scale.com/v1/tasks"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = ScaleAISource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestScaleAIPipelineWiring:
    def test_resumable_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock(team_id=1, job_id="job", logger=MagicMock())
        manager = ScaleAISource().get_resumable_source_manager(inputs)
        assert manager._data_class is ScaleAIResumeConfig

    def test_source_for_pipeline_forwards_inputs(self) -> None:
        config = MagicMock(api_key="live_key")
        manager = MagicMock()
        inputs = MagicMock(
            schema_name="tasks",
            logger=MagicMock(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
            incremental_field="updated_at",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.source.scale_ai_source"
        ) as mock_source:
            ScaleAISource().source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "live_key"
        assert kwargs["endpoint"] == "tasks"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"
        assert kwargs["incremental_field"] == "updated_at"

    def test_source_for_pipeline_drops_cursor_on_full_refresh(self) -> None:
        # A stale watermark must not leak into a full-refresh run and silently filter it.
        config = MagicMock(api_key="live_key")
        inputs = MagicMock(
            schema_name="projects",
            logger=MagicMock(),
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
            incremental_field=None,
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.source.scale_ai_source"
        ) as mock_source:
            ScaleAISource().source_for_pipeline(config, MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
