from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source import DatadogSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datadog import (
    DatadogSourceConfig,
)


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

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"

    def test_version_metadata_declares_v2_default_and_deprecates_v1(self) -> None:
        # The repin migration and the in-product deprecation banner both key off this metadata;
        # the registry invariant test only checks generic invariants, not v1-deprecated / v2-default.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

        deprecated = {d.version: d for d in self.source.deprecated_versions}
        assert set(deprecated) == {"v1"}
        assert deprecated["v1"].sunset_at is None
