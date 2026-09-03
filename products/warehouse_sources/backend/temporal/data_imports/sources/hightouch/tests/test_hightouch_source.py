import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hightouch import (
    HightouchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.settings import (
    ENDPOINTS,
    SYNC_RUNS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.source import HightouchSource


class TestHightouchSource:
    def setup_method(self) -> None:
        self.source = HightouchSource()
        self.team_id = 123
        self.config = HightouchSourceConfig(api_key="hightouch-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Hightouch"
        assert config.label == "Hightouch"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/hightouch.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hightouch"

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Config tables have no server-side timestamp filter, so they are full refresh only.
        for name in ("syncs", "models", "sources", "destinations"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

        # sync_runs supports incremental via the server-side `after` filter on startedAt,
        # and is merge-only because in-progress runs mutate and the lookback re-reads them.
        assert schemas["sync_runs"].supports_incremental is True
        assert schemas["sync_runs"].supports_append is False
        assert [f["field"] for f in schemas["sync_runs"].incremental_fields] == ["startedAt"]
        assert schemas["sync_runs"].default_incremental_lookback_seconds == SYNC_RUNS_LOOKBACK_SECONDS

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sync_runs"])
        assert len(schemas) == 1
        assert schemas[0].name == "sync_runs"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.hightouch.com/api/v1/syncs",
            "403 Client Error: Forbidden for url: https://api.hightouch.com/api/v1/syncs",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.hightouch.com/api/v1/syncs" for key in non_retryable
        )
