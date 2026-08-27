import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tinyemail import (
    TinyemailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.source import TinyemailSource


class TestTinyemailSource:
    def setup_method(self) -> None:
        self.source = TinyemailSource()
        self.team_id = 123
        self.config = TinyemailSourceConfig(api_key="tinyemail-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Tinyemail"
        assert config.label == "tinyEmail"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tinyemail"
        assert config.iconPath == "/static/services/tinyemail.png"
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # tinyEmail has no server-side timestamp filter on any endpoint, so nothing
        # may advertise incremental or append sync.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "observed_error,expected_non_retryable",
        [
            ("401 Client Error: Unauthorized for url: https://api.tinyemail.com/v1/campaign", True),
            ("403 Client Error: Forbidden for url: https://api.tinyemail.com/v1/contacts", True),
            ("429 Client Error: Too Many Requests for url: https://api.tinyemail.com/v1/campaign", False),
            ("500 Server Error: Internal Server Error for url: https://api.tinyemail.com/v1/campaign", False),
        ],
    )
    def test_non_retryable_errors(self, observed_error: str, expected_non_retryable: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expected_non_retryable
