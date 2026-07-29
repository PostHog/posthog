from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.mistral_ai import MistralAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source import MistralAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = overrides.get("schema_name", "files")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    inputs.incremental_field = overrides.get("incremental_field", None)
    inputs.logger = MagicMock()
    return inputs


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert MistralAISource().source_type == ExternalDataSourceType.MISTRALAI

    def test_api_key_field_is_required_secret_password(self) -> None:
        # A non-secret key field would persist the API key in plaintext job inputs.
        fields = MistralAISource().get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.required is True
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD

    def test_alpha_and_docs_url(self) -> None:
        config = MistralAISource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # docsUrl filename must match the posthog.com doc (kebab-case) for the source page to resolve.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/mistral-ai"


class TestGetSchemas:
    @parameterized.expand(
        [
            ("fine_tuning_jobs", True),
            ("batch_jobs", True),
            ("files", False),
            ("models", False),
            ("agents", False),
            ("conversations", False),
            ("libraries", False),
        ]
    )
    def test_incremental_only_where_server_filter_exists(self, endpoint: str, supports_incremental: bool) -> None:
        # Only fine-tuning and batch jobs expose a server-side created_after filter; the rest must ship
        # full refresh, never advertise incremental they can't honor.
        schemas = {s.name: s for s in MistralAISource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []

    @parameterized.expand([("agents", False), ("conversations", False), ("libraries", False), ("files", True)])
    def test_beta_endpoints_off_by_default(self, endpoint: str, should_sync_default: bool) -> None:
        schemas = {s.name: s for s in MistralAISource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].should_sync_default is should_sync_default

    def test_names_filter(self) -> None:
        schemas = MistralAISource().get_schemas(MagicMock(), team_id=1, names=["files", "models"])
        assert {s.name for s in schemas} == {"files", "models"}

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials must stay True so posthog.com renders the Supported tables section.
        source = MistralAISource()
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        assert {t["name"] for t in tables} == {s.name for s in source.get_schemas(source._placeholder_config(), 0)}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Mistral AI API key"))])
    def test_maps_probe_result(self, _name: str, probe: bool, expected: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source.validate_mistral_ai_credentials",
            return_value=probe,
        ):
            result = MistralAISource().validate_credentials(MagicMock(api_key="sk-x"), team_id=1)
        assert result == expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.mistral.ai/v1/files?page=0"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.mistral.ai/v1/batch/jobs"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in MistralAISource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.mistral.ai/v1/files"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.mistral.ai/v1/files"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in MistralAISource().get_non_retryable_errors())


class TestPipelinePlumbing:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = MistralAISource().get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MistralAIResumeConfig

    def test_source_for_pipeline_forwards_incremental_inputs(self) -> None:
        source = MistralAISource()
        inputs = _make_inputs(
            schema_name="batch_jobs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1_772_000_000,
            incremental_field="created_at",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source.mistral_ai_source"
        ) as mock_source:
            source.source_for_pipeline(MagicMock(api_key="sk-x"), MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "batch_jobs"
        assert kwargs["api_key"] == "sk-x"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1_772_000_000

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        # Passing a stale watermark on a full-refresh run would build a bogus created_after filter.
        source = MistralAISource()
        inputs = _make_inputs(
            schema_name="files", should_use_incremental_field=False, db_incremental_field_last_value=1_772_000_000
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source.mistral_ai_source"
        ) as mock_source:
            source.source_for_pipeline(MagicMock(api_key="sk-x"), MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
