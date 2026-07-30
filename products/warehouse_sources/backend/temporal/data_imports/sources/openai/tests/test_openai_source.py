from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai import OpenAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.source import OpenAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_USAGE_ENDPOINTS = [
    "usage_completions",
    "usage_embeddings",
    "usage_moderations",
    "usage_images",
    "usage_audio_speeches",
    "usage_audio_transcriptions",
    "usage_vector_stores",
    "usage_code_interpreter_sessions",
]

_ENTITY_ENDPOINTS = [
    "projects",
    "users",
    "invites",
    "admin_api_keys",
    "project_users",
    "project_service_accounts",
    "project_api_keys",
    "project_rate_limits",
]


class TestOpenAISourceConfig:
    def test_source_type(self) -> None:
        assert OpenAISource().source_type == ExternalDataSourceType.OPENAI

    def test_config_exposes_single_secret_api_key_field(self) -> None:
        config = OpenAISource().get_source_config
        assert config.name == SchemaExternalDataSourceType.OPEN_AI
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/openai"
        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["api_key"]
        assert fields[0].secret is True and fields[0].required is True


class TestOpenAISchemas:
    def test_all_endpoints_present(self) -> None:
        names = {s.name for s in OpenAISource().get_schemas(MagicMock(), team_id=1)}
        assert names == {*_USAGE_ENDPOINTS, *_ENTITY_ENDPOINTS, "costs", "audit_logs"}

    @parameterized.expand([(endpoint,) for endpoint in [*_USAGE_ENDPOINTS, "costs"]])
    def test_bucketed_endpoints_are_incremental_on_start_time(self, endpoint: str) -> None:
        # The usage/costs endpoints have a genuine server-side time filter (start_time). Buckets
        # get restated, so a trailing-day lookback re-reads them and merge dedupes.
        schema = next(s for s in OpenAISource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["start_time"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 24

    def test_audit_logs_are_incremental_on_effective_at(self) -> None:
        schema = next(s for s in OpenAISource().get_schemas(MagicMock(), team_id=1) if s.name == "audit_logs")
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["effective_at"]

    @parameterized.expand([(endpoint,) for endpoint in _ENTITY_ENDPOINTS])
    def test_entity_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # No updated-since filter exists on the entity lists, so they must not advertise incremental.
        schema = next(s for s in OpenAISource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = OpenAISource().get_schemas(MagicMock(), team_id=1, names=["usage_completions"])
        assert [s.name for s in schemas] == ["usage_completions"]


class TestOpenAIResumableManager:
    def test_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = OpenAISource().get_resumable_source_manager(inputs)
        assert manager._data_class is OpenAIResumeConfig


class TestOpenAISourceForPipeline:
    def _response(self, endpoint: str) -> object:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = None
        config = MagicMock(api_key="sk-admin-test")
        return OpenAISource().source_for_pipeline(config, MagicMock(), inputs)

    @parameterized.expand(
        [
            ("usage_completions", ["id"], "datetime", "asc"),
            ("costs", ["id"], "datetime", "asc"),
            ("users", ["id"], "datetime", "asc"),
            ("project_users", ["project_id", "id"], "datetime", "asc"),
            ("project_rate_limits", ["project_id", "id"], None, "asc"),
            # Audit logs return newest-first, so the watermark must only commit at sync completion.
            ("audit_logs", ["id"], "datetime", "desc"),
        ]
    )
    def test_primary_keys_partitioning_and_sort_mode(
        self, endpoint: str, primary_keys: list[str], partition_mode: str | None, sort_mode: str
    ) -> None:
        response = self._response(endpoint)
        assert response.name == endpoint  # type: ignore[attr-defined]
        assert response.primary_keys == primary_keys  # type: ignore[attr-defined]
        assert response.sort_mode == sort_mode  # type: ignore[attr-defined]
        assert response.partition_mode == partition_mode  # type: ignore[attr-defined]


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog => the source opts into publishing its table list to public docs.
        assert OpenAISource().lists_tables_without_credentials is True
        tables = OpenAISource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert "usage_completions" in names and "costs" in names
        costs = next(t for t in tables if t["name"] == "costs")
        assert "Incremental" in costs["sync_methods"]
        assert costs["description"]  # canonical description is surfaced
