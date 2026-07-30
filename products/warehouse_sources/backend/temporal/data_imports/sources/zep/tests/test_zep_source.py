from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZepSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.source import ZepSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.zep import ZepResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(schema_name: str = "users") -> Any:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    return inputs


class TestZepSource:
    def setup_method(self) -> None:
        self.source = ZepSource()
        self.team_id = 7

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZEP

    def test_source_config_exposes_api_key_password_field(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Zep"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zep"

        assert len(config.fields) == 1
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Zep has no server-side timestamp filter, so nothing is incremental/append.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["threads"])
        assert [s.name for s in schemas] == ["threads"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Zep API key"))])
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: tuple[bool, str | None]) -> None:
        config = ZepSourceConfig(api_key="z_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zep.source.validate_zep_credentials",
            return_value=probe_ok,
        ):
            assert self.source.validate_credentials(config, self.team_id) == expected

    @parameterized.expand(["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors_cover_auth_failures(self, expected_key_prefix: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(k.startswith(expected_key_prefix) for k in keys)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZepResumeConfig

    def test_source_for_pipeline_plumbs_api_key_and_schema(self) -> None:
        config = ZepSourceConfig(api_key="z_secret")
        manager = MagicMock()
        inputs = _inputs(schema_name="thread_messages")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zep.source.zep_source"
        ) as mock_zep_source:
            self.source.source_for_pipeline(config, manager, inputs)

        mock_zep_source.assert_called_once()
        kwargs = mock_zep_source.call_args.kwargs
        assert kwargs["api_key"] == "z_secret"
        assert kwargs["endpoint"] == "thread_messages"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(ENDPOINTS).issubset(descriptions.keys())

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True: get_schemas is a static catalog, so public docs
        # can render the table list with no live connection.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
