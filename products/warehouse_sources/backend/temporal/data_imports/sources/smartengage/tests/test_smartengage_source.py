import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

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
        assert config.releaseStatus == ReleaseStatus.ALPHA
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

    @pytest.mark.parametrize(
        "observed_error,expected_non_retryable",
        [
            ("401 Client Error: Unauthorized for url: https://api.smartengage.com/avatars/list", True),
            ("403 Client Error: Forbidden for url: https://api.smartengage.com/tags/list", True),
            ("500 Server Error: Internal Server Error for url: https://api.smartengage.com/avatars/list", False),
        ],
    )
    def test_non_retryable_errors(self, observed_error: str, expected_non_retryable: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expected_non_retryable
