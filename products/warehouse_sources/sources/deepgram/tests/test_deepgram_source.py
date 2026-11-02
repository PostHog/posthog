from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
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
            ("usage_breakdown_incremental", "usage_breakdown", True),
            ("billing_breakdown_incremental", "billing_breakdown", True),
            ("members_full_refresh", "members", False),
            ("balances_full_refresh", "balances", False),
            ("projects_full_refresh", "projects", False),
        ]
    )
    def test_incremental_support_matches_the_server_side_date_filter(
        self, _name: str, endpoint: str, incremental: bool
    ) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is incremental

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, api_ok: bool, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=200 if api_ok else 401)]) as network:
            ok, _error = self.source.validate_credentials(DeepgramSourceConfig(api_key="k"), team_id=1)
        assert ok is expected
        assert network.requests_log[0].path == "/v1/projects"

    @parameterized.expand([("incremental_on", True), ("incremental_off", False)])
    def test_source_for_pipeline_gates_last_value_on_incremental(self, _name: str, use_incremental: bool) -> None:
        config = DeepgramSourceConfig(api_key="k")
        result = SourceDriver(self.source, config).run(
            "requests",
            [
                ScriptedResponse(json={"projects": [{"project_id": "p1"}]}),
                ScriptedResponse(json={"requests": []}),
            ],
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value="2026-01-01",
        )

        assert result.raised is None
        assert result.requests[-1].headers["authorization"] == "Token k"
        # The last value is only forwarded when the sync is actually incremental.
        assert result.requests[-1].param("start") == ("2026-01-01" if use_incremental else None)
