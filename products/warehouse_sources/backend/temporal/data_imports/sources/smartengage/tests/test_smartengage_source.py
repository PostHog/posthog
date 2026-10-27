from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, ReleaseStatus
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartengage import (
    SmartEngageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.source import SmartEngageSource


class TestSmartEngageSource:
    def setup_method(self) -> None:
        self.source = SmartEngageSource()
        self.team_id = 123
        self.config = SmartEngageSourceConfig(api_key="se_test_key")

    def test_get_source_config_is_released(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SmartEngage"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        # The source must stay visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.BETA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/smartengage"

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # SmartEngage has no server-side timestamp filters, so no endpoint may advertise
        # incremental sync — a client-side "incremental" would silently miss nothing but
        # cost the same as full refresh and corrupt sync-type expectations.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
