from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowplowSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.snowplow import SnowplowResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.source import SnowplowSource
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
        incremental_field="startTime" if use_incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestSnowplowSource:
    def setup_method(self) -> None:
        self.source = SnowplowSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SNOWPLOW

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields.keys()) == {"organization_id", "api_key_id", "api_key"}
        # Only the API key is confidential; the org ID and key ID must stay editable/visible.
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True
        assert fields["organization_id"].secret is False
        assert fields["api_key_id"].secret is False
        assert all(f.required for f in fields.values())

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # unreleasedSource hides the connector from every user; a finished source must not carry it.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/snowplow"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True

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

    @parameterized.expand([("valid", (True, None)), ("invalid", (False, "bad credentials"))])
    def test_validate_credentials(self, _name: str, probe_result: tuple[bool, str | None]) -> None:
        config = SnowplowSourceConfig(organization_id="org-1", api_key_id="key-id", api_key="key")
        with patch.object(source_module, "validate_snowplow_credentials", return_value=probe_result) as mock_probe:
            ok, error = self.source.validate_credentials(config, team_id=1)
        assert (ok, error) == probe_result
        assert mock_probe.call_args.args[:3] == ("org-1", "key-id", "key")

    @parameterized.expand(
        [
            (
                "token_mint_auth_failure",
                "Snowplow API authentication failed: the API key or API key ID is invalid or has been revoked.",
            ),
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://console.snowplowanalytics.com/api/msc/v1/organizations/org/jobs/v1/runs",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://console.snowplowanalytics.com/api/msc/v1/organizations/org/users",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("job_runs"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SnowplowResumeConfig

    def test_source_for_pipeline_plumbs_credentials_and_endpoint(self) -> None:
        config = SnowplowSourceConfig(organization_id="org-1", api_key_id="key-id", api_key="key")
        inputs = _source_inputs("job_runs", last_value="2026-07-10T00:00:00Z", use_incremental=True)
        with patch.object(source_module, "snowplow_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["organization_id"] == "org-1"
        assert kwargs["api_key_id"] == "key-id"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "job_runs"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-10T00:00:00Z"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        # Passing a stale watermark on a full-refresh run would wrongly narrow the time window.
        config = SnowplowSourceConfig(organization_id="org-1", api_key_id="key-id", api_key="key")
        inputs = _source_inputs("job_runs", last_value="2026-07-10T00:00:00Z", use_incremental=False)
        with patch.object(source_module, "snowplow_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Drift here (an endpoint renamed in settings but not here) silently drops the curated docs
        # and falls back to LLM enrichment, so keep the two in lockstep.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
