from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source import ConvertKitSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.convertkit import (
    ConvertKitSourceConfig,
)


class TestConvertKitSource:
    def setup_method(self) -> None:
        self.source = ConvertKitSource()
        self.team_id = 123
        self.config = ConvertKitSourceConfig(api_key="kit_test")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
            ("403 Client Error: Forbidden for url: https://api.clerk.com/v1/users",),
        ]
    )
    def test_non_retryable_errors_do_not_match_other_vendors(self, other_vendor_error: str) -> None:
        assert not any(key in other_vendor_error for key in self.source.get_non_retryable_errors())
