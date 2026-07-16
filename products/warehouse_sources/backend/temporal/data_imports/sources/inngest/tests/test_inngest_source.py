from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InngestSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.inngest import InngestResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.source import InngestSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


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

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.INNGEST

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["signing_key", "environment"]
        signing_key, environment = config.fields
        assert isinstance(signing_key, SourceFieldInputConfig)
        assert signing_key.type == SourceFieldInputConfigType.PASSWORD
        assert signing_key.required is True
        assert signing_key.secret is True
        assert isinstance(environment, SourceFieldInputConfig)
        assert environment.required is False
        assert environment.secret is False

    def test_source_config_is_alpha_and_unreleased(self) -> None:
        # The source ships hidden (unreleasedSource) and labelled alpha; a regression that flipped
        # either would expose an unfinished connector to every user.
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/inngest"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True

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

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.inngest.com/v1/events?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.inngest.com/v2/envs"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("events"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is InngestResumeConfig

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

    def test_source_for_pipeline_normalizes_blank_environment_to_none(self) -> None:
        # An empty-string environment must not be sent as an X-Inngest-Env header — the API would
        # try to resolve a branch environment named "".
        config = InngestSourceConfig(signing_key="signkey-prod-test", environment="")
        with patch.object(source_module, "inngest_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), _source_inputs("events"))
        assert mock_source.call_args.kwargs["environment"] is None

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        # A stale watermark on a full-refresh run would wrongly narrow the events window.
        config = InngestSourceConfig(signing_key="signkey-prod-test")
        inputs = _source_inputs("events", last_value="2026-07-01T00:00:00Z", use_incremental=False)
        with patch.object(source_module, "inngest_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Drift here (an endpoint renamed in settings but not here) silently drops the curated docs
        # and falls back to LLM enrichment, so keep the two in lockstep.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
