from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opnpayments import (
    OpnPaymentsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source import OpnPaymentsSource


class TestOpnPaymentsSource:
    def setup_method(self):
        self.source = OpnPaymentsSource()
        self.team_id = 123
        self.config = OpnPaymentsSourceConfig(secret_key="skey_test_123")

    def test_default_api_version_is_supported_and_not_deprecated(self):
        assert self.source.default_version in self.source.supported_versions
        assert self.source.get_version_deprecation(self.source.default_version) is None
