from unittest.mock import MagicMock

from parameterized import parameterized

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
