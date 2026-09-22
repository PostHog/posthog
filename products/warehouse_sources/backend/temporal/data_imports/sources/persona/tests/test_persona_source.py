from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.persona import (
    PersonaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.source import PersonaSource


class TestPersonaGetSchemas:
    @parameterized.expand(
        [
            # (endpoint, supports_incremental, supports_append)
            ("inquiries", True, True),
            ("verifications", True, True),
            ("accounts", True, True),
            ("cases", True, True),
            ("transactions", True, True),
            # Events are an immutable audit log — append only, never merged.
            ("events", False, True),
            # Inquiry templates are config data with no created-at window — full refresh only.
            ("inquiry_templates", False, False),
        ]
    )
    def test_endpoint_sync_capabilities(self, endpoint: str, incremental: bool, append: bool) -> None:
        schemas = {s.name: s for s in PersonaSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is incremental
        assert schema.supports_append is append

    def test_names_filter(self) -> None:
        schemas = PersonaSource().get_schemas(MagicMock(), team_id=1, names=["cases"])
        assert [s.name for s in schemas] == ["cases"]

    def test_verifications_is_not_preselected(self) -> None:
        # Verifications cost one extra request per inquiry, so they're opt-in while everything else
        # stays pre-selected.
        schemas = {s.name: s for s in PersonaSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas["verifications"].should_sync_default is False
        assert all(s.should_sync_default for name, s in schemas.items() if name != "verifications")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the public docs render the table list.
        assert PersonaSource.lists_tables_without_credentials is True
        tables = PersonaSource().get_documented_tables()
        assert {t["name"] for t in tables} == {
            "inquiries",
            "verifications",
            "accounts",
            "cases",
            "transactions",
            "events",
            "inquiry_templates",
        }


class TestPersonaValidateCredentials:
    @parameterized.expand(
        [
            # (http_status, schema_name, expected_ok)
            ("valid_key", 200, None, True),
            ("bad_key", 401, None, False),
            # 403 at source-create is accepted (key valid, may just lack a scope for one resource).
            ("missing_scope_at_create", 403, None, True),
            # 403 for a specific schema means the key can't sync that resource.
            ("missing_scope_for_schema", 403, "inquiries", False),
            ("network_error", 0, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.persona.source.validate_persona_credentials",
            return_value=status,
        ):
            ok, _msg = PersonaSource().validate_credentials(
                PersonaSourceConfig(api_key="persona_test"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
