from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    ENDPOINTS,
    LIMITED_RETENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source import DatadogSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datadog import (
    DatadogSourceConfig,
)

# Endpoint -> the cursor field it advertises. Only endpoints with a genuine server-side time
# filter belong here; everything else must come back full-refresh only.
INCREMENTAL_ENDPOINTS = {
    "logs": "timestamp",
    "audit_logs": "timestamp",
    "events": "timestamp",
    "usage_hourly": "timestamp",
    "usage_summary": "date",
    "usage_historical_cost": "date",
}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "logs",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestDatadogSource:
    def setup_method(self) -> None:
        self.source = DatadogSource()
        self.team_id = 123
        self.config = DatadogSourceConfig(api_key="dd-api", application_key="dd-app", site="datadoghq.com")

    def test_site_is_a_connection_host_field(self) -> None:
        # Changing the site must force the secrets to be re-entered so they're never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["site"]

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name, cursor_field in INCREMENTAL_ENDPOINTS.items():
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert schemas[name].incremental_fields == [
                {
                    "label": cursor_field,
                    "type": "datetime",
                    "field": cursor_field,
                    "field_type": "datetime",
                }
            ]

        for name in set(ENDPOINTS) - set(INCREMENTAL_ENDPOINTS):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_retention_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name in LIMITED_RETENTION_ENDPOINTS:
            assert schemas[name].description is not None
        assert schemas["dashboards"].description is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_version_metadata_declares_v2_default_and_deprecates_v1(self) -> None:
        # The repin migration and the in-product deprecation banner both key off this metadata;
        # the registry invariant test only checks generic invariants, not v1-deprecated / v2-default.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

        deprecated = {d.version: d for d in self.source.deprecated_versions}
        assert set(deprecated) == {"v1"}
        assert deprecated["v1"].sunset_at is None
