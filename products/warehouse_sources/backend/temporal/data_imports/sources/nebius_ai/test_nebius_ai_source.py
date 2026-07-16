from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import NebiusAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.source import NebiusAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestNebiusAISourceConfig:
    def test_source_type(self) -> None:
        assert NebiusAISource().source_type == ExternalDataSourceType.NEBIUSAI

    def test_config_has_single_api_key_password_field(self) -> None:
        fields = NebiusAISource().get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == "password"
        assert field.required is True

    def test_docs_url_matches_published_doc_slug(self) -> None:
        # docsUrl must match the posthog.com doc filename so the docs link resolves.
        assert NebiusAISource().get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/nebius-ai"


class TestNebiusAISchemas:
    def test_exposes_expected_endpoints(self) -> None:
        schemas = NebiusAISource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert {s.name for s in schemas} == {"models", "files", "batches", "fine_tuning_jobs"}

    def test_every_endpoint_is_full_refresh_only(self) -> None:
        # No endpoint has a server-side timestamp filter, so incremental/append must stay off to
        # avoid advertising a mode that would cost the same as a full refresh every run.
        for schema in NebiusAISource().get_schemas(MagicMock(), team_id=1):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter_narrows_the_list(self) -> None:
        schemas = NebiusAISource().get_schemas(MagicMock(), team_id=1, names=["files"])
        assert [s.name for s in schemas] == ["files"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so the public docs table catalog can render.
        source = NebiusAISource()
        assert source.lists_tables_without_credentials is True
        assert {t["name"] for t in source.get_documented_tables()} == set(ENDPOINTS)


class TestNebiusAICanonicalDescriptions:
    def test_descriptions_cover_every_endpoint(self) -> None:
        descriptions = NebiusAISource().get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        assert all("id" in descriptions[name].get("columns", {}) for name in ENDPOINTS)


class TestNebiusAIValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Your Nebius AI API key is invalid or has expired.")),
            ("transient", (False, "Could not reach Nebius AI: boom")),
        ]
    )
    def test_validate_credentials_forwards_transport_result(self, _name: str, transport_result: tuple) -> None:
        # The source must forward the transport verdict verbatim so transient and permission messages
        # are not collapsed into a generic "invalid key".
        config = MagicMock()
        config.api_key = "nbk_test"
        with patch.object(source_module, "validate_nebius_ai_credentials", return_value=transport_result):
            assert NebiusAISource().validate_credentials(config, team_id=1) == transport_result


class TestNebiusAINonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.tokenfactory.nebius.com/v1/models"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.tokenfactory.nebius.com/v1/batches"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        errors = NebiusAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in errors)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.tokenfactory.nebius.com/v1/files",
            ),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.tokenfactory.nebius.com"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed_error: str) -> None:
        errors = NebiusAISource().get_non_retryable_errors()
        assert not any(key in observed_error for key in errors)


class TestNebiusAIResumableWiring:
    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = NebiusAISource().get_resumable_source_manager(inputs)
        assert manager._data_class is NebiusAIResumeConfig

    def test_source_for_pipeline_forwards_api_key_and_schema(self) -> None:
        config = MagicMock()
        config.api_key = "nbk_test"
        inputs = MagicMock()
        inputs.schema_name = "batches"
        manager = MagicMock()

        with patch.object(source_module, "nebius_ai_source") as mock_source:
            NebiusAISource().source_for_pipeline(config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "nbk_test"
        assert kwargs["endpoint"] == "batches"
        assert kwargs["resumable_source_manager"] is manager


class TestNebiusAIRegistration:
    def test_source_is_registered(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

        source = SourceRegistry.get_source(ExternalDataSourceType.NEBIUSAI)
        assert isinstance(source, NebiusAISource)

    def test_get_resumable_manager_namespace(self) -> None:
        # Sanity: the manager's data class survives a with_namespace() sibling (used for isolated state).
        inputs = MagicMock()
        manager = NebiusAISource().get_resumable_source_manager(inputs)
        assert manager.with_namespace("models")._data_class is NebiusAIResumeConfig
