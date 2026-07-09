from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import (
    ENDPOINTS,
    TOGETHER_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.source import TogetherAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "together_test") -> Any:
    return source_module.TogetherAISourceConfig(api_key=api_key)


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert TogetherAISource().source_type == ExternalDataSourceType.TOGETHERAI

    def test_config_declares_secret_api_key_field(self) -> None:
        fields = TogetherAISource().get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert TogetherAISource.lists_tables_without_credentials is True


class TestGetSchemas:
    def test_returns_all_endpoints_full_refresh_only(self) -> None:
        schemas = TogetherAISource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No pagination and no server-side timestamp filters, so nothing advertises incremental/append.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_names_filter_restricts_output(self) -> None:
        schemas = TogetherAISource().get_schemas(_config(), team_id=1, names=["fine_tunes"])
        assert [s.name for s in schemas] == ["fine_tunes"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = TogetherAISource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        evaluations = next(t for t in tables if t["name"] == "evaluations")
        assert evaluations["primary_keys"] == ["workflow_id"]
        assert "Full refresh" in evaluations["sync_methods"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "fine_tunes", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "get_status_code", return_value=status):
            ok, _err = TogetherAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_probes_requested_schema_endpoint(self) -> None:
        with patch.object(source_module, "get_status_code", return_value=200) as mock_probe:
            TogetherAISource().validate_credentials(_config(), team_id=1, schema_name="batches")
        assert mock_probe.call_args.args == ("together_test", "batches")

    def test_transport_failure_returns_actionable_error(self) -> None:
        with patch.object(source_module, "get_status_code", side_effect=Exception("boom")):
            ok, err = TogetherAISource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.together.xyz/v1/fine-tunes",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.together.xyz/v1/endpoints?type=dedicated",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = TogetherAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.together.xyz/v1/models",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.together.xyz/v1/batches",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.together.xyz', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = TogetherAISource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestSourceForPipeline:
    def test_plumbs_config_and_schema_through(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "fine_tunes"
        with patch.object(source_module, "together_ai_source") as mock_source:
            TogetherAISource().source_for_pipeline(_config(api_key="together_k"), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "together_k"
        assert kwargs["endpoint"] == "fine_tunes"


class TestCanonicalDescriptions:
    def test_every_endpoint_has_a_canonical_description(self) -> None:
        descriptions = TogetherAISource().get_canonical_descriptions()
        for endpoint in TOGETHER_AI_ENDPOINTS:
            assert endpoint in descriptions
            entry = descriptions[endpoint]
            # Primary key columns must be documented so enrichment doesn't fall back to the LLM for them.
            for pk in TOGETHER_AI_ENDPOINTS[endpoint].primary_keys:
                assert pk in entry["columns"]
