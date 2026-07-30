from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RoarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.roark import RoarkResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import ENDPOINTS, ROARK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.source import RoarkSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRoarkSource:
    def setup_method(self) -> None:
        self.source = RoarkSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ROARK

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_source_config_shape(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Roark"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/roark"

    def test_source_config_has_secret_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any("401 Client Error" in key for key in errors)
        assert any("403 Client Error" in key for key in errors)

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(RoarkSourceConfig(api_key="k"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == ROARK_ENDPOINTS[schema.name].primary_keys

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(RoarkSourceConfig(api_key="k"), self.team_id, names=["call", "chat"])
        assert {s.name for s in schemas} == {"call", "chat"}

    @parameterized.expand([(True, True, None), (False, False, "Invalid Roark API key")])
    def test_validate_credentials(self, valid: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch.object(source_module, "validate_roark_credentials", return_value=valid):
            ok, msg = self.source.validate_credentials(RoarkSourceConfig(api_key="k"), self.team_id)
        assert ok is expected_ok
        assert msg == expected_msg

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RoarkResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "call"
        config = RoarkSourceConfig(api_key="secret-key")
        manager = MagicMock()

        with patch.object(source_module, "roark_source") as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["endpoint"] == "call"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_keys_match_endpoints(self) -> None:
        # Canonical descriptions are keyed by the schema/endpoint name get_schemas returns.
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        for table in tables:
            assert "Full refresh" in table["sync_methods"]
