import pytest

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rapid7insightvm import (
    Rapid7InsightvmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.source import (
    Rapid7InsightvmSource,
)

SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.source"


class TestRapid7InsightvmSource:
    def setup_method(self):
        self.source = Rapid7InsightvmSource()
        self.team_id = 123
        self.config = Rapid7InsightvmSourceConfig(api_key="key", region="us")

    def test_get_source_config_is_released_alpha(self):
        config = self.source.get_source_config
        # Guards against the scaffold's `unreleasedSource=True` (which hides the connector entirely)
        # regressing back in — a finished source must be visible.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    def test_non_retryable_errors_include_auth(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint advertises incremental — the v4 timestamp filter is unverified, so all ship full refresh.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
