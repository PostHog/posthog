from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.easybill import EasybillResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.source import EasybillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easybill import (
    EasybillSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestEasybillSourceClass:
    def setup_method(self) -> None:
        self.source = EasybillSource()
        self.config = EasybillSourceConfig(api_key="key")
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.EASYBILL

    def test_source_config_has_password_api_key_field(self) -> None:
        config = self.source.get_source_config
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/easybill"
        fields = config.fields or []
        assert len(fields) == 1
        assert fields[0].name == "api_key"
        assert fields[0].type == "password"

    def test_no_unreleased_flag(self) -> None:
        # A finished source ships visible: unreleasedSource must not be set at all.
        assert self.source.get_source_config.unreleasedSource is None

    @parameterized.expand([("401 Client Error",), ("403 Client Error",)])
    def test_non_retryable_errors(self, expected_key_prefix: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(k.startswith(expected_key_prefix) for k in keys)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_documents_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["Documents"].supports_incremental is True
        assert [f["field"] for f in schemas["Documents"].incremental_fields] == ["edited_at"]
        for name, schema in schemas.items():
            if name != "Documents":
                assert schema.supports_incremental is False, name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Documents", "Customers"])
        assert {s.name for s in schemas} == {"Documents", "Customers"}

    def test_documented_tables_render_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["Documents"]["description"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid easybill API key"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_easybill_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected

    def test_get_resumable_source_manager_bound_to_data_class(self) -> None:
        inputs = mock.Mock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EasybillResumeConfig

    def test_source_for_pipeline_plumbs_incremental_args(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "Documents"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"
        manager = mock.Mock()

        with mock.patch.object(source_module, "easybill_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mocked.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "Documents"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "Customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01"
        manager = mock.Mock()

        with mock.patch.object(source_module, "easybill_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None


class TestCanonicalDescriptions:
    def test_keys_are_all_real_endpoints(self) -> None:
        # A canonical entry keyed by a name that isn't an endpoint would silently never render.
        descriptions: dict[str, Any] = EasybillSource().get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "Documents" in descriptions


if __name__ == "__main__":
    pytest.main([__file__])
