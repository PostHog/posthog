from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openai import OpenAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.source import OpenAISource

_USAGE_ENDPOINTS = [
    "usage_completions",
    "usage_embeddings",
    "usage_moderations",
    "usage_images",
    "usage_audio_speeches",
    "usage_audio_transcriptions",
    "usage_vector_stores",
    "usage_code_interpreter_sessions",
    "usage_web_search_calls",
    "usage_file_search_calls",
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


class TestOpenAISchemas:
    @parameterized.expand([(endpoint,) for endpoint in [*_USAGE_ENDPOINTS, "costs"]])
    def test_bucketed_endpoints_are_incremental_on_start_time(self, endpoint: str) -> None:
        # The usage/costs endpoints have a genuine server-side time filter (start_time). Buckets
        # get restated, so a trailing-day lookback re-reads them and merge dedupes.
        schema = next(s for s in OpenAISource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["start_time"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 24

    @parameterized.expand([(endpoint,) for endpoint in _ENTITY_ENDPOINTS])
    def test_entity_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # No updated-since filter exists on the entity lists, so they must not advertise incremental.
        schema = next(s for s in OpenAISource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False


class TestOpenAISourceForPipeline:
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
        result = SourceDriver(OpenAISource(), OpenAISourceConfig(api_key="sk-admin-test")).run(
            endpoint,
            [ScriptedResponse(json={"data": [], "has_more": False})],
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.sort_mode == sort_mode
        assert result.response.partition_mode == partition_mode
