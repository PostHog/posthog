from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source import DatadogSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datadog import (
    DatadogSourceConfig,
)

INCREMENTAL_ENDPOINTS = {"logs", "audit_logs", "events"}


class TestDatadogSource:
    def setup_method(self) -> None:
        self.source = DatadogSource()
        self.team_id = 123
        self.config = DatadogSourceConfig(api_key="dd-api", application_key="dd-app", site="datadoghq.com")

    def test_version_metadata_declares_v2_default_and_deprecates_v1(self) -> None:
        # The repin migration and the in-product deprecation banner both key off this metadata;
        # the registry invariant test only checks generic invariants, not v1-deprecated / v2-default.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

        deprecated = {d.version: d for d in self.source.deprecated_versions}
        assert set(deprecated) == {"v1"}
        assert deprecated["v1"].sunset_at is None
