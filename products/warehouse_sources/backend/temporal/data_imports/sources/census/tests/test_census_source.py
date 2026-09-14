import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.census.source import CensusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.census import CensusSourceConfig


class TestCensusSource:
    def setup_method(self) -> None:
        self.source = CensusSource()
        self.team_id = 123
        self.config = CensusSourceConfig(api_key="census-key", region="us")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Census"
        assert config.label == "Census (Fivetran)"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/census.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/census"

    def test_get_schemas_all_full_refresh(self) -> None:
        # Census has no server-side timestamp filter on any list endpoint, so nothing supports
        # incremental sync.
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.getcensus.com/api/v1/syncs",
            "403 Client Error: Forbidden for url: https://app.getcensus.com/api/v1/syncs",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://app.getcensus.com/api/v1/syncs" for key in non_retryable
        )
