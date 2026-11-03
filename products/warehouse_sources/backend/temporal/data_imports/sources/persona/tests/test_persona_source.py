from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.persona import (
    PersonaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.persona import (
    PERSONA_API_VERSION_2026_09_29,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.source import PersonaSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.persona.source"


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
            ("inquiry_templates", False, False),
            ("inquiry_template_versions", False, False),
            ("reports", False, False),
            ("workflow_runs", False, False),
            ("inquiry_sessions", False, False),
        ]
    )
    def test_endpoint_sync_capabilities(self, endpoint: str, incremental: bool, append: bool) -> None:
        schemas = {s.name: s for s in PersonaSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is incremental
        assert schema.supports_append is append


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


class TestPersonaVersionDispatch:
    def test_new_sources_default_to_2026_09_29(self) -> None:
        assert PersonaSource.default_version == PERSONA_API_VERSION_2026_09_29
        assert UNVERSIONED_API_VERSION in PersonaSource.supported_versions

    @parameterized.expand(
        [
            ("legacy_pin", UNVERSIONED_API_VERSION, UNVERSIONED_API_VERSION),
            ("2026_09_29_pin", PERSONA_API_VERSION_2026_09_29, PERSONA_API_VERSION_2026_09_29),
            ("no_pin", None, PERSONA_API_VERSION_2026_09_29),
        ]
    )
    def test_pin_reaches_sync_and_validation(self, _name: str, pin: str | None, expected: str) -> None:
        inputs = MagicMock(api_version=pin, schema_name="inquiries", should_use_incremental_field=False)
        with (
            patch(f"{SOURCE_MODULE}.persona_source") as persona_source,
            patch(f"{SOURCE_MODULE}.validate_persona_credentials", return_value=200) as validate,
        ):
            PersonaSource().source_for_pipeline(PersonaSourceConfig(api_key="persona_test"), MagicMock(), inputs)
            PersonaSource().validate_credentials(
                PersonaSourceConfig(api_key="persona_test"), team_id=1, api_version=pin
            )

        assert persona_source.call_args.kwargs["api_version"] == expected
        validate.assert_called_once_with("persona_test", expected)
