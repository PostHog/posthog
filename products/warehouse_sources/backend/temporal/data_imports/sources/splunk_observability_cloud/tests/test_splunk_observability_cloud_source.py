from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SplunkObservabilityCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.settings import (
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source import (
    SplunkObservabilityCloudSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.splunk_observability_cloud import (
    SplunkObservabilityCloudResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "detectors",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSplunkObservabilityCloudSource:
    def setup_method(self) -> None:
        self.source = SplunkObservabilityCloudSource()
        self.team_id = 123
        self.config = SplunkObservabilityCloudSourceConfig(realm="us0", access_token="test-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SPLUNKOBSERVABILITYCLOUD

    def test_realm_is_a_connection_host_field(self) -> None:
        # The realm becomes the request hostname the stored token is sent to, so
        # changing it must force the token to be re-entered.
        assert self.source.connection_host_fields == ["realm"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "SplunkObservabilityCloud"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/splunk-observability-cloud"

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["realm", "access_token", "signalflow_program"]

        realm_field, token_field, program_field = fields
        assert realm_field.type == SourceFieldInputConfigType.TEXT
        assert realm_field.required is True

        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

        assert program_field.type == SourceFieldInputConfigType.TEXTAREA
        assert program_field.required is False

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the two endpoints with a server-side time filter (detector events'
        # from/to, SignalFlow's start/stop) advertise incremental sync.
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"detector_events", "metric_time_series"}
        for name in incremental:
            assert [f["field"] for f in schemas[name].incremental_fields] == ["timestamp"]

    def test_get_schemas_default_sync_selection(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # dimensions (unbounded volume) and metric_time_series (needs the optional
        # SignalFlow program) must not be force-enabled by one-shot setup.
        off_by_default = {name for name, s in schemas.items() if not s.should_sync_default}
        assert off_by_default == {"dimensions", "metric_time_series"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["detectors"])
        assert [s.name for s in schemas] == ["detectors"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_known_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Keyed by endpoint name: an entry for a non-existent endpoint silently never
        # applies, and a missing entry falls back to paid LLM enrichment.
        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            (
                (False, "Invalid Splunk Observability Cloud access token or realm"),
                False,
                "Invalid Splunk Observability Cloud access token or realm",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source.validate_splunk_observability_cloud_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.realm, self.config.access_token)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SplunkObservabilityCloudResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source.splunk_observability_cloud_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        config = SplunkObservabilityCloudSourceConfig(
            realm="eu0", access_token="tok", signalflow_program="data('cpu.utilization').publish()"
        )
        inputs = _make_inputs(
            schema_name="detector_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01",
            incremental_field="timestamp",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once_with(
            realm="eu0",
            access_token="tok",
            endpoint="detector_events",
            logger=inputs.logger,
            resumable_source_manager=manager,
            signalflow_program="data('cpu.utilization').publish()",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01",
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source.splunk_observability_cloud_source"
    )
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A leftover watermark from a previous incremental config must not narrow a
        # full-refresh run.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
