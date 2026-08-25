import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teachable import (
    TeachableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.settings import (
    ENDPOINTS,
    TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.source import TeachableSource


class TestTeachableSource:
    def setup_method(self) -> None:
        self.source = TeachableSource()
        self.team_id = 123
        self.config = TeachableSourceConfig(api_key="teachable-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Teachable"
        assert config.label == "Teachable"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/teachable.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Only /transactions has a server-side time filter (`start`); everything else is
        # full refresh.
        assert schemas["transactions"].supports_incremental is True
        assert [f["field"] for f in schemas["transactions"].incremental_fields] == ["created_at"]
        assert schemas["transactions"].default_incremental_lookback_seconds == TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS

        for name in ("users", "courses", "course_enrollments", "pricing_plans"):
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions"])
        assert [s.name for s in schemas] == ["transactions"]

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("401 Client Error: Unauthorized for url: https://developers.teachable.com/v1/users", True),
            ("403 Client Error: Forbidden for url: https://developers.teachable.com/v1/courses", True),
            ("500 Server Error: Internal Server Error for url: https://developers.teachable.com/v1/users", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match
