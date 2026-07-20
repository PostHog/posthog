from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FireworksAIResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    ENDPOINTS,
    FIREWORKS_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.source import FireworksAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "fw_test", account_id: str = "my-account") -> Any:
    return source_module.FireworksAISourceConfig(api_key=api_key, account_id=account_id)


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert FireworksAISource().source_type == ExternalDataSourceType.FIREWORKSAI

    def test_config_declares_secret_api_key_and_account_id_fields(self) -> None:
        fields = FireworksAISource().get_source_config.fields
        assert [f.name for f in fields] == ["api_key", "account_id"]
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert FireworksAISource.lists_tables_without_credentials is True

    def test_account_id_change_requires_secret_reentry(self) -> None:
        # Dropping this override would let an editor retarget a preserved API key at another
        # Fireworks account without re-entering it (the update serializer keys off this list).
        assert FireworksAISource().connection_host_fields == ["account_id"]


class TestGetSchemas:
    def test_returns_all_endpoints_full_refresh_only(self) -> None:
        schemas = FireworksAISource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Server-side timestamp filtering is unverified (AIP-160 filter fields undocumented),
        # so nothing may advertise incremental/append.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_names_filter_restricts_output(self) -> None:
        schemas = FireworksAISource().get_schemas(_config(), team_id=1, names=["models"])
        assert [s.name for s in schemas] == ["models"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = FireworksAISource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        models = next(t for t in tables if t["name"] == "models")
        assert models["primary_keys"] == ["name"]
        assert "Full refresh" in models["sync_methods"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("account_not_found", 404, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "models", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "get_status_code", return_value=status):
            ok, _err = FireworksAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_invalid_account_id_rejected_without_probe(self) -> None:
        with patch.object(source_module, "get_status_code") as mock_probe:
            ok, err = FireworksAISource().validate_credentials(_config(account_id="bad id!"), team_id=1)
        assert ok is False
        assert err is not None
        mock_probe.assert_not_called()

    def test_pasted_resource_prefix_is_normalized_before_probe(self) -> None:
        with patch.object(source_module, "get_status_code", return_value=200) as mock_probe:
            ok, _err = FireworksAISource().validate_credentials(_config(account_id="accounts/my-account"), team_id=1)
        assert ok is True
        assert mock_probe.call_args.args == ("fw_test", "my-account", None)

    def test_transport_failure_returns_actionable_error(self) -> None:
        with patch.object(source_module, "get_status_code", side_effect=Exception("boom")):
            ok, err = FireworksAISource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.fireworks.ai/v1/accounts/my-account/models",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.fireworks.ai/v1/accounts/my-account/datasets",
            ),
            (
                "account_not_found",
                "404 Client Error: Not Found for url: https://api.fireworks.ai/v1/accounts/nope/models",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FireworksAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.fireworks.ai/v1/accounts/my-account/models",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.fireworks.ai/v1/accounts/my-account/models",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.fireworks.ai', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = FireworksAISource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestSourceForPipeline:
    def test_plumbs_config_schema_and_manager_through(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "models"
        manager = MagicMock()
        with patch.object(source_module, "fireworks_ai_source") as mock_source:
            FireworksAISource().source_for_pipeline(_config(api_key="fw_k", account_id="acct"), manager, inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "fw_k"
        assert kwargs["account_id"] == "acct"
        assert kwargs["endpoint"] == "models"
        assert kwargs["resumable_source_manager"] is manager

    def test_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.team_id = 1
        inputs.job_id = "job-1"
        manager = FireworksAISource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FireworksAIResumeConfig


class TestCanonicalDescriptions:
    def test_every_endpoint_has_a_canonical_description(self) -> None:
        descriptions = FireworksAISource().get_canonical_descriptions()
        for endpoint in FIREWORKS_AI_ENDPOINTS:
            assert endpoint in descriptions
            entry = descriptions[endpoint]
            # Primary key columns must be documented so enrichment doesn't fall back to the LLM for them.
            for pk in FIREWORKS_AI_ENDPOINTS[endpoint].primary_keys:
                assert pk in entry["columns"]
