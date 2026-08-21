from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sigmacomputing import (
    SigmaComputingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.settings import REGION_HOSTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.source import (
    REGION_OPTIONS,
    SigmaComputingSource,
)


class TestSigmaComputingSource:
    def setup_method(self) -> None:
        self.source = SigmaComputingSource()
        self.team_id = 123
        self.config = SigmaComputingSourceConfig(client_id="client-id", client_secret="client-secret", region="gcp_us")

    def test_region_options_constant_matches_settings(self) -> None:
        assert {option.value for option in REGION_OPTIONS} == set(REGION_HOSTS)
