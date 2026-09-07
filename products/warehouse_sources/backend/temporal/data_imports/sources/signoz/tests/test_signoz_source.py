import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.signoz import SigNozSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.settings import (
    ENDPOINTS,
    LIMITED_RETENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.source import SigNozSource

INCREMENTAL_ENDPOINTS = {"logs", "traces"}


class TestSigNozSource:
    def setup_method(self) -> None:
        self.source = SigNozSource()
        self.team_id = 123
        self.config = SigNozSourceConfig(host="example.signoz.io", api_key="signoz-key")

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert schemas[name].incremental_fields == [
                {
                    "label": "timestamp",
                    "type": "datetime",
                    "field": "timestamp",
                    "field_type": "datetime",
                }
            ]

        for name in set(ENDPOINTS) - INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_retention_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name in LIMITED_RETENTION_ENDPOINTS:
            assert schemas[name].description is not None
        assert schemas["dashboards"].description is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["traces"])
        assert len(schemas) == 1
        assert schemas[0].name == "traces"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_new_sources_default_to_v5(self) -> None:
        # New sources (no pin) must be created on the current SigNoz query_range API version.
        assert self.source.default_version == "v5"
        assert self.source.resolve_api_version(None) == "v5"

    @pytest.mark.parametrize("version", ["v1", "v5"])
    def test_existing_pin_is_honored(self, version: str) -> None:
        # Existing instances keep their pinned version verbatim after the default bump, so their
        # syncs are unaffected.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version

    @pytest.mark.parametrize("version", ["v1", "v5"])
    def test_no_version_is_deprecated(self, version: str) -> None:
        # This is a plain update, not a sunset: neither label is deprecated, so the in-product
        # deprecation banner must stay dark for existing v1 pins.
        assert self.source.get_version_deprecation(version) is None
