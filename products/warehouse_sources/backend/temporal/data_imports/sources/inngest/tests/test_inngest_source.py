from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.inngest import (
    InngestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.source import InngestSource


class TestInngestSource:
    def setup_method(self) -> None:
        self.source = InngestSource()

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["environments"])
        assert [s.name for s in schemas] == ["environments"]

    @parameterized.expand(
        [
            # Events are immutable, so append is the only incremental-style mode; run rows mutate
            # (status settles after the run ends), so they are merge-only. Everything else is a
            # small inventory with no server-side timestamp filter and syncs as full refresh.
            ("events", False, True, ["received_at"]),
            ("function_runs", True, False, ["event_received_at"]),
            ("cancellations", False, False, []),
            ("environments", False, False, []),
            ("webhooks", False, False, []),
            ("event_keys", False, False, []),
            ("signing_keys", False, False, []),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, supports_append: bool, incremental_fields: list[str]
    ) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields

    def test_function_runs_re_read_a_trailing_window(self) -> None:
        # Runs fetched while still Running keep a stale status unless each incremental sync
        # re-reads a trailing window; dropping the default lookback would freeze them forever.
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == "function_runs")
        assert schema.default_incremental_lookback_seconds == 3600

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        config = InngestSourceConfig(signing_key="signkey-prod-test", environment="branch-env")
        with patch.object(source_module, "validate_inngest_credentials", return_value=probe_result) as mock_probe:
            ok, error = self.source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
        mock_probe.assert_called_once_with("signkey-prod-test", "branch-env")

    def test_defaults_new_sources_to_v2(self) -> None:
        # New sources are stamped with default_version; this locks the bump to v2 (the generic
        # registry invariant only checks default == supported_versions[-1], so a revert to v1
        # would pass it).
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"
