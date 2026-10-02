from django.test import override_settings

from products.warehouse_sources.backend.temporal.data_imports.redis_url import data_warehouse_redis_url


class TestDataWarehouseRedisUrl:
    @override_settings(DATA_WAREHOUSE_REDIS_HOST="dwh-redis", DATA_WAREHOUSE_REDIS_PORT="6380")
    def test_uses_dedicated_instance_when_configured(self) -> None:
        assert data_warehouse_redis_url() == "redis://dwh-redis:6380/"

    @override_settings(DATA_WAREHOUSE_REDIS_HOST=None, DATA_WAREHOUSE_REDIS_PORT=None, REDIS_URL="redis://shared:6379/")
    def test_falls_back_to_shared_redis_when_unconfigured(self) -> None:
        # An install without a dedicated warehouse Redis used to have no valid fallback here,
        # turning every lock/idempotency/row-tracking call into a reported "missing env vars"
        # exception instead of using the always-configured shared instance.
        assert data_warehouse_redis_url() == "redis://shared:6379/"
