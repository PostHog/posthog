from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recharge import (
    RechargeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.source import RechargeSource


def _config(api_key: str = "sk_test") -> RechargeSourceConfig:
    return RechargeSourceConfig(api_key=api_key)


class TestRechargeSourceGetSchemas:
    def test_products_is_full_refresh_only(self) -> None:
        # The 2021-11 `/products` endpoint has no `sort_by` or `*_min` filter, so
        # it can't sync incrementally — it must be advertised as full-refresh.
        schemas = RechargeSource().get_schemas(_config(), team_id=1)
        products = next(s for s in schemas if s.name == "products")
        assert products.supports_incremental is False
        assert products.incremental_fields == []
