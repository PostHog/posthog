import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.eventzilla import (
    EventzillaResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.source import EventzillaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EventzillaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestEventzillaSourceClass:
    def setup_method(self) -> None:
        self.source = EventzillaSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.EVENTZILLA

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/eventzilla"

    def test_source_config_has_single_secret_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_all_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == {"events", "categories", "users", "attendees", "transactions", "tickets"}
        # Eventzilla has no server-side updated-since filter, so nothing supports incremental/append.
        for schema in schemas:
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name
            assert schema.incremental_fields == [], schema.name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["events", "attendees"])
        assert {s.name for s in schemas} == {"events", "attendees"}

    def test_fan_out_endpoints_carry_a_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=1)}
        assert schemas["attendees"].description is not None
        assert schemas["events"].description is None

    @pytest.mark.parametrize("valid,expected", [(True, (True, None)), (False, (False, "Invalid Eventzilla API key"))])
    def test_validate_credentials(self, valid: bool, expected: tuple[bool, str | None]) -> None:
        config = EventzillaSourceConfig(api_key="key")
        with patch.object(source_module, "validate_eventzilla_credentials", return_value=valid):
            assert self.source.validate_credentials(config, team_id=1) == expected

    @pytest.mark.parametrize("status", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors_cover_auth_failures(self, status: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(status in key for key in keys)

    def test_resumable_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(MagicMock())
        assert manager._data_class is EventzillaResumeConfig

    def test_source_for_pipeline_plumbs_key_and_schema(self) -> None:
        config = EventzillaSourceConfig(api_key="secret-key")
        inputs = MagicMock()
        inputs.schema_name = "transactions"
        manager = MagicMock()
        with patch.object(source_module, "eventzilla_source") as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)
        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager

    def test_documented_tables_render_without_credentials(self) -> None:
        # `lists_tables_without_credentials` is on, so public docs get the full static catalog.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == {
            "events",
            "categories",
            "users",
            "attendees",
            "transactions",
            "tickets",
        }
