from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.source import DeepgramSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deepgram import (
    DeepgramSourceConfig,
)


class TestDeepgramSourceClass:
    def setup_method(self) -> None:
        self.source = DeepgramSource()

    @parameterized.expand(
        [
            ("requests_incremental", "requests", True),
            ("members_full_refresh", "members", False),
            ("balances_full_refresh", "balances", False),
            ("projects_full_refresh", "projects", False),
        ]
    )
    def test_only_requests_supports_incremental(self, _name: str, endpoint: str, incremental: bool) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is incremental

    def test_schemas_expose_composite_primary_keys(self) -> None:
        # Fan-out children must key on [project_id, ...] to stay unique table-wide; a regression to a
        # bare id would seed duplicate rows across projects.
        schemas = {s.name: s.detected_primary_keys for s in self.source.get_schemas(MagicMock(), team_id=1)}
        assert schemas["members"] == ["project_id", "member_id"]
        assert schemas["requests"] == ["project_id", "request_id"]

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["requests"])
        assert [s.name for s in schemas] == ["requests"]

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, api_ok: bool, expected: bool) -> None:
        with patch.object(source_module, "validate_deepgram_credentials", return_value=api_ok):
            ok, _error = self.source.validate_credentials(DeepgramSourceConfig(api_key="k"), team_id=1)
        assert ok is expected
