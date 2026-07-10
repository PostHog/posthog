from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.aviator import AviatorResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.source import AviatorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AviatorSourceConfig
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
        incremental_field="date" if use_incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestAviatorSource:
    def setup_method(self) -> None:
        self.source = AviatorSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AVIATOR

    def test_source_config_has_a_single_secret_token_field(self) -> None:
        config = self.source.get_source_config
        assert len(config.fields) == 1
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_source_config_is_alpha_and_unreleased(self) -> None:
        # The source ships hidden (unreleasedSource) and labelled alpha; a regression that flipped
        # either would expose an unfinished connector to every user.
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aviator"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True

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

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.aviator.co/api/v1/repo"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.aviator.co/api/v1/queue/stats"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("repositories"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AviatorResumeConfig

    def test_source_for_pipeline_plumbs_token_and_endpoint(self) -> None:
        config = AviatorSourceConfig(api_token="av_uat_test")
        inputs = _source_inputs("merge_queue_analytics", last_value="2026-06-10", use_incremental=True)
        with patch.object(source_module, "aviator_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "av_uat_test"
        assert kwargs["endpoint"] == "merge_queue_analytics"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-10"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        # Passing a stale watermark on a full-refresh run would wrongly narrow the analytics window.
        config = AviatorSourceConfig(api_token="av_uat_test")
        inputs = _source_inputs("queue_stats", last_value="2026-06-10", use_incremental=False)
        with patch.object(source_module, "aviator_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Drift here (an endpoint renamed in settings but not here) silently drops the curated docs
        # and falls back to LLM enrichment, so keep the two in lockstep.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
