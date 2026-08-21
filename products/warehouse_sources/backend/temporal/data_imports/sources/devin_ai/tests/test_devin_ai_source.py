from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import DevinAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.source import DevinAISource


def _config(api_key: str = "cog_test", org_id: str = "org-abc") -> Any:
    return source_module.DevinAISourceConfig(api_key=api_key, org_id=org_id)


class TestGetSchemas:
    def test_members_table_is_discovered_full_refresh_with_user_id_key(self) -> None:
        # The set-equality assertions above compare get_schemas against the same dict the schemas come
        # from, so only an explicit name check catches the members table going missing from discovery.
        schemas = {s.name: s for s in DevinAISource().get_schemas(_config(), team_id=1)}
        members = schemas["members"]
        assert members.supports_incremental is False
        assert members.supports_append is False
        # user_id is the merge key: anything else would duplicate members across full refreshes.
        assert members.detected_primary_keys == ["user_id"]
        assert members.should_sync_default is True


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


def test_resume_config_default_is_none() -> None:
    assert DevinAIResumeConfig().after is None
