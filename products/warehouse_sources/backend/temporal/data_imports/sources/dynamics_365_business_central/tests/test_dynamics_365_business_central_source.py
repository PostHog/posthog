from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.settings import (
    BUSINESS_CENTRAL_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.source import (
    Dynamics365BusinessCentralSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365businesscentral import (
    Dynamics365BusinessCentralSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.source"


class TestDynamics365BusinessCentralSource:
    def setup_method(self) -> None:
        self.source = Dynamics365BusinessCentralSource()
        self.team_id = 123
        self.config = Dynamics365BusinessCentralSourceConfig(
            tenant_id="contoso.onmicrosoft.com",
            environment="production",
            client_id="client-id",
            client_secret="client-secret",
        )

    def test_api_version_matches_the_path_the_code_calls(self) -> None:
        # The version is a request path segment, so the pin must be the one the transport builds.
        assert self.source.supported_versions == ("v2.0",)
        assert self.source.default_version == "v2.0"
        assert self.source.api_docs_url.startswith("https://")
        assert self.source.resolve_api_version(None) == "v2.0"

    def test_canonical_descriptions_key_off_schema_names(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions).issubset(set(ENDPOINTS))
        for name, entry in descriptions.items():
            assert entry["docs_url"].startswith("https://learn.microsoft.com/"), name
            if BUSINESS_CENTRAL_ENDPOINTS[name].company_scoped:
                # Every fan-out table's key starts with the stamped company id, so it must be documented.
                assert "company_id" in entry["columns"], name
