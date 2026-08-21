from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aviator import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.source import AviatorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aviator import (
    AviatorSourceConfig,
)


class TestAviatorSource:
    def setup_method(self) -> None:
        self.source = AviatorSource()

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["queue_stats"])
        assert [s.name for s in schemas] == ["queue_stats"]

    @parameterized.expand(
        [
            # Only the date-windowed analytics endpoint has a genuine server-side filter, so it is the
            # only incremental table; the snapshot/list endpoints are full refresh.
            ("merge_queue_analytics", True, ["date"]),
            ("repositories", False, []),
            ("queued_pull_requests", False, []),
            ("queue_stats", False, []),
            ("config_history", False, []),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, incremental_fields: list[str]
    ) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        # Analytics rows are revised daily aggregates deduped by merge, so append is never offered.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        config = AviatorSourceConfig(api_token="av_uat_test")
        with patch.object(source_module, "validate_aviator_credentials", return_value=probe_result):
            ok, error = self.source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
