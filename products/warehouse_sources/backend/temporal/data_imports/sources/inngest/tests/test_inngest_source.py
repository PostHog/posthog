from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.inngest import (
    InngestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.source import InngestSource


def _source_inputs(
    schema_name: str, last_value: Optional[object] = None, use_incremental: bool = False
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=use_incremental,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="received_at" if use_incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestInngestSource:
    def setup_method(self) -> None:
        self.source = InngestSource()

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True

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
            ("runs", True, False, ["queuedAt"]),
            ("functions", False, False, []),
            ("session_keys", False, False, []),
            ("sessions", False, False, []),
            ("session_runs", False, False, []),
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

    @parameterized.expand([("function_runs",), ("runs",)])
    def test_run_tables_re_read_a_trailing_window(self, endpoint: str) -> None:
        # Runs fetched while still Running keep a stale status unless each incremental sync
        # re-reads a trailing window; dropping the default lookback would freeze them forever.
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.default_incremental_lookback_seconds == 3600

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        config = InngestSourceConfig(signing_key="signkey-prod-test", environment="branch-env")
        with patch.object(source_module, "validate_inngest_credentials", return_value=probe_result) as mock_probe:
            ok, error = self.source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
        mock_probe.assert_called_once_with("signkey-prod-test", "branch-env")

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.inngest.com/v1/events?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.inngest.com/v2/envs"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_source_for_pipeline_plumbs_credentials_and_endpoint(self) -> None:
        config = InngestSourceConfig(signing_key="signkey-prod-test", environment="branch-env")
        inputs = _source_inputs("events", last_value="2026-07-01T00:00:00Z", use_incremental=True)
        with patch.object(source_module, "inngest_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["signing_key"] == "signkey-prod-test"
        assert kwargs["environment"] == "branch-env"
        assert kwargs["endpoint"] == "events"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01T00:00:00Z"

    def test_defaults_new_sources_to_v2(self) -> None:
        # New sources are stamped with default_version; this locks the bump to v2 (the generic
        # registry invariant only checks default == supported_versions[-1], so a revert to v1
        # would pass it).
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

    @parameterized.expand(
        [
            ("no_pin_resolves_to_default", None, "v2"),
            ("v1_pin_honored", "v1", "v1"),
            ("v2_pin_honored", "v2", "v2"),
        ]
    )
    def test_source_for_pipeline_threads_the_resolved_api_version(
        self, _name: str, pin: Optional[str], expected: str
    ) -> None:
        # A pinned source must sync under its own version, not the default — dropping the resolve
        # would leave every source reading the default version's paths.
        config = InngestSourceConfig(signing_key="signkey-prod-test")
        inputs = _source_inputs("webhooks")
        inputs.api_version = pin
        with patch.object(source_module, "inngest_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["api_version"] == expected
