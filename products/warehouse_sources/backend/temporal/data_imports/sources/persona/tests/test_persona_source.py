from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PersonaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.persona import PersonaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.source import PersonaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPersonaSourceConfig:
    def test_source_type(self) -> None:
        assert PersonaSource().source_type == ExternalDataSourceType.PERSONA

    def test_config_is_alpha_and_unreleased(self) -> None:
        config = PersonaSource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True

    def test_api_key_field_is_a_secret_password(self) -> None:
        fields = PersonaSource().get_source_config.fields
        assert fields is not None
        api_key = next(f for f in fields if getattr(f, "name", None) == "api_key")
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True


class TestPersonaGetSchemas:
    @parameterized.expand(
        [
            # (endpoint, supports_incremental, supports_append)
            ("inquiries", True, True),
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

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the public docs render the table list.
        assert PersonaSource.lists_tables_without_credentials is True
        tables = PersonaSource().get_documented_tables()
        assert {t["name"] for t in tables} == {
            "inquiries",
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


class TestPersonaNonRetryableErrors:
    def test_auth_errors_are_non_retryable(self) -> None:
        errors = PersonaSource().get_non_retryable_errors()
        assert any("401" in key and "api.withpersona.com" in key for key in errors)
        assert any("403" in key and "api.withpersona.com" in key for key in errors)


class TestPersonaResumableWiring:
    def test_resumable_manager_bound_to_persona_resume_config(self) -> None:
        manager = PersonaSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PersonaResumeConfig

    def test_source_for_pipeline_passes_schema_name_and_api_key(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "cases"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = "created_at"

        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.persona.source.persona_source"
        ) as mock_source:
            PersonaSource().source_for_pipeline(PersonaSourceConfig(api_key="persona_test"), manager, inputs)

        _args, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "persona_test"
        assert kwargs["endpoint"] == "cases"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "inquiry_templates"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = None

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.persona.source.persona_source"
        ) as mock_source:
            PersonaSource().source_for_pipeline(PersonaSourceConfig(api_key="persona_test"), MagicMock(), inputs)

        _args, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
