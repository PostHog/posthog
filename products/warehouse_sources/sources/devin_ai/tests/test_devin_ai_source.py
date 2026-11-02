from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import DevinAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.source import DevinAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.devinai import (
    DevinAISourceConfig,
)


def _config(api_key: str = "cog_test", org_id: str = "org-abc") -> DevinAISourceConfig:
    return DevinAISourceConfig(api_key=api_key, org_id=org_id)


class TestSourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert DevinAISource.lists_tables_without_credentials is True

    def test_connection_host_fields_force_secret_reentry_on_org_change(self) -> None:
        # Changing org_id retargets the stored API key at a different Devin org, so it must count as a
        # host field — editing it forces the user to re-enter the key.
        assert DevinAISource().connection_host_fields == ["org_id"]


class TestGetSchemas:
    @parameterized.expand(
        [
            # Secret metadata is opt-in, and session_messages costs one request per session in the
            # org's whole history — neither should turn on for a user who just wanted sessions.
            ("secrets", False),
            ("session_messages", False),
            ("sessions", True),
            ("session_insights", True),
            ("consumption_daily", True),
        ]
    )
    def test_costly_and_sensitive_tables_are_opt_in(self, endpoint: str, expected_default: bool) -> None:
        schemas = {s.name: s for s in DevinAISource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is expected_default


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
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, _err = DevinAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert network.requests_log[0].path == "/v3/organizations/org-abc/sessions"


def test_resume_config_default_is_none() -> None:
    assert DevinAIResumeConfig().after is None
