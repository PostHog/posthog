from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.source import SnowplowSource


class TestSnowplowSource:
    def setup_method(self) -> None:
        self.source = SnowplowSource()

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["job_runs"])
        assert [s.name for s in schemas] == ["job_runs"]

    @parameterized.expand(
        [
            # Only the time-windowed endpoints have a genuine server-side filter; the small
            # current-state catalogs are full refresh.
            ("job_runs", True, ["startTime"]),
            ("job_run_steps", True, ["runStartTime"]),
            ("failed_event_metrics", True, ["window"]),
            ("pipelines", False, []),
            ("users", False, []),
            ("data_models", False, []),
            ("data_structures", False, []),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, incremental_fields: list[str]
    ) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        # Rows are revised upstream (run states transition, buckets accumulate) and incremental
        # re-pulls a lookback window that merge dedupes, so append is never offered.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields
