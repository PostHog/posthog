from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.fulcrum import FulcrumResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.source import FulcrumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FulcrumSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFulcrumSourceClass:
    def setup_method(self) -> None:
        self.source = FulcrumSource()
        self.config = FulcrumSourceConfig(api_token="token")
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FULCRUM

    def test_source_config_has_password_token_field(self) -> None:
        config = self.source.get_source_config
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/fulcrum"
        fields = config.fields or []
        assert len(fields) == 1
        assert fields[0].name == "api_token"
        assert fields[0].type == "password"

    @parameterized.expand([("401 Client Error",), ("403 Client Error",)])
    def test_non_retryable_errors(self, expected_key_prefix: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(k.startswith(expected_key_prefix) for k in keys)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_records_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["records"].supports_incremental is True
        assert [f["field"] for f in schemas["records"].incremental_fields] == ["updated_at"]
        for name, schema in schemas.items():
            if name != "records":
                assert schema.supports_incremental is False, name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["records", "forms"])
        assert {s.name for s in schemas} == {"records", "forms"}

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials must expose the static catalog for public docs, with the
        # curated record description flowing through.
        assert self.source.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["records"]["description"]
        assert tables["photos"]["primary_keys"] == []  # detected keys only populated at sync time

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Fulcrum API token"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_fulcrum_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected

    def test_get_resumable_source_manager_bound_to_data_class(self) -> None:
        inputs = mock.Mock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FulcrumResumeConfig

    def test_source_for_pipeline_plumbs_incremental_args(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "records"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2021-01-01"
        manager = mock.Mock()

        with mock.patch.object(source_module, "fulcrum_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mocked.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "records"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2021-01-01"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "forms"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2021-01-01"
        manager = mock.Mock()

        with mock.patch.object(source_module, "fulcrum_source") as mocked:
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None


class TestCanonicalDescriptions:
    def test_keys_are_all_real_endpoints(self) -> None:
        # A canonical entry keyed by a name that isn't an endpoint would silently never render.
        descriptions: dict[str, Any] = FulcrumSource().get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "records" in descriptions


if __name__ == "__main__":
    pytest.main([__file__])
