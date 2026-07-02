from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import DevinAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import (
    DEVIN_AI_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.source import DevinAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "cog_test", org_id: str = "org-abc") -> Any:
    return source_module.DevinAISourceConfig(api_key=api_key, org_id=org_id)


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert DevinAISource().source_type == ExternalDataSourceType.DEVINAI

    def test_config_declares_api_key_and_org_id_fields(self) -> None:
        fields = DevinAISource().get_source_config.fields
        names = {f.name for f in fields}
        assert names == {"api_key", "org_id"}
        api_key_field = next(f for f in fields if f.name == "api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert DevinAISource.lists_tables_without_credentials is True

    def test_connection_host_fields_force_secret_reentry_on_org_change(self) -> None:
        # Changing org_id retargets the stored API key at a different Devin org, so it must count as a
        # host field — editing it forces the user to re-enter the key.
        assert DevinAISource().connection_host_fields == ["org_id"]


class TestGetSchemas:
    def test_returns_all_endpoints_full_refresh_only(self) -> None:
        schemas = DevinAISource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No verified server-side timestamp filter, so nothing advertises incremental/append.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_secrets_off_by_default_others_on(self) -> None:
        schemas = {s.name: s for s in DevinAISource().get_schemas(_config(), team_id=1)}
        assert schemas["secrets"].should_sync_default is False
        assert schemas["sessions"].should_sync_default is True

    def test_names_filter_restricts_output(self) -> None:
        schemas = DevinAISource().get_schemas(_config(), team_id=1, names=["sessions"])
        assert [s.name for s in schemas] == ["sessions"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = DevinAISource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        sessions = next(t for t in tables if t["name"] == "sessions")
        assert sessions["primary_keys"] == ["session_id"]
        assert "Full refresh" in sessions["sync_methods"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "sessions", False),
            ("org_not_found", 404, None, False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "validate_devin_ai_credentials", return_value=status):
            ok, _err = DevinAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_probes_requested_schema_endpoint(self) -> None:
        with patch.object(source_module, "validate_devin_ai_credentials", return_value=200) as mock_validate:
            DevinAISource().validate_credentials(_config(), team_id=1, schema_name="playbooks")
        assert mock_validate.call_args.args[2] == "playbooks"

    def test_unknown_schema_falls_back_to_sessions_probe(self) -> None:
        with patch.object(source_module, "validate_devin_ai_credentials", return_value=200) as mock_validate:
            DevinAISource().validate_credentials(_config(), team_id=1, schema_name="not_a_table")
        assert mock_validate.call_args.args[2] == "sessions"

    def test_transport_failure_is_not_fatal_message(self) -> None:
        with patch.object(source_module, "validate_devin_ai_credentials", side_effect=Exception("boom")):
            ok, err = DevinAISource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.devin.ai/v3/organizations/org-abc/sessions?first=200",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.devin.ai/v3/organizations/org-abc/secrets"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = DevinAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.devin.ai/v3/organizations/org-abc/sessions",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.devin.ai/v3/organizations/org-abc/sessions",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.devin.ai', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = DevinAISource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = DevinAISource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)

    def test_source_for_pipeline_plumbs_config_through(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "sessions"
        manager = MagicMock()
        with patch.object(source_module, "devin_ai_source") as mock_source:
            DevinAISource().source_for_pipeline(_config(api_key="cog_k", org_id="org-x"), manager, inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "cog_k"
        assert kwargs["org_id"] == "org-x"
        assert kwargs["endpoint"] == "sessions"
        assert kwargs["resumable_source_manager"] is manager


class TestCanonicalDescriptions:
    def test_every_endpoint_has_a_canonical_description(self) -> None:
        descriptions = DevinAISource().get_canonical_descriptions()
        for endpoint in DEVIN_AI_ENDPOINTS:
            assert endpoint in descriptions
            entry = descriptions[endpoint]
            # Primary key columns must be documented so enrichment doesn't fall back to the LLM for them.
            for pk in DEVIN_AI_ENDPOINTS[endpoint].primary_keys:
                assert pk in entry["columns"]


def test_resume_config_default_is_none() -> None:
    assert DevinAIResumeConfig().after is None
