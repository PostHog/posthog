from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source import BillComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billcom import (
    BillComSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source"


class TestBillComSource:
    def setup_method(self) -> None:
        self.source = BillComSource()
        self.team_id = 123
        self.config = BillComSourceConfig(
            username="finance@acme.com",
            password="pw",
            organization_id="org-1",
            dev_key="dev-key",
            environment="production",
        )

    def test_api_version_is_pinned_to_the_path_the_source_calls(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.resolve_api_version(None) == "v3"

    def test_every_endpoint_advertises_incremental_fields(self) -> None:
        assert set(INCREMENTAL_FIELDS) == set(ENDPOINTS)
