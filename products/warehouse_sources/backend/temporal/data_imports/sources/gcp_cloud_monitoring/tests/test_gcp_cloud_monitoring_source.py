import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.gcp_cloud_monitoring import (
    GcpCloudMonitoringResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.settings import (
    ENDPOINTS,
    INCREMENTAL_LOOKBACK_SECONDS,
    PRIMARY_KEYS,
    TIME_SERIES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.source import (
    GcpCloudMonitoringSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.source"
FILTER = 'resource.type="consumed_api"'

# Only some members of the source-field union declare `required` — a switch group and an SSH
# tunnel carry no such flag. Narrowing to the ones that do keeps a field that changes shape
# visible as a KeyError instead of passing silently.
_FIELDS_WITH_REQUIRED = (SourceFieldFileUploadConfig, SourceFieldInputConfig, SourceFieldSelectConfig)


def _required_by_field_name() -> dict[str, bool]:
    return {
        field.name: field.required
        for field in GcpCloudMonitoringSource().get_source_config.fields
        if isinstance(field, _FIELDS_WITH_REQUIRED)
    }


def _config(**overrides):
    key_file = MagicMock()
    key_file.project_id = overrides.get("key_file_project_id", "key-project")
    key_file.private_key = "pk"
    key_file.private_key_id = "pkid"
    key_file.client_email = "sa@example.com"
    key_file.token_uri = "https://not-google.example/token"

    config = MagicMock()
    config.key_file = key_file
    config.project_id = overrides.get("project_id", "")
    config.metric_filter = overrides.get("metric_filter", FILTER)
    config.per_series_aligner = overrides.get("per_series_aligner", "")
    config.alignment_period_seconds = overrides.get("alignment_period_seconds", None)
    config.cross_series_reducer = overrides.get("cross_series_reducer", "")
    config.group_by_fields = overrides.get("group_by_fields", "")
    return config


def _inputs(schema_name: str = TIME_SERIES, **overrides):
    inputs = MagicMock()
    inputs.schema_name = schema_name
    inputs.team_id = 1
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2026-08-13T00:00:00Z")
    return inputs


class TestSourceIdentity:
    def test_source_type(self):
        assert GcpCloudMonitoringSource().source_type == ExternalDataSourceType.GCPCLOUDMONITORING

    def test_config_is_a_monitoring_source_with_alpha_release_status(self):
        config = GcpCloudMonitoringSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_the_implemented_source_is_no_longer_hidden_from_users(self):
        assert not GcpCloudMonitoringSource().get_source_config.unreleasedSource

    def test_key_file_and_filter_are_required(self):
        required = _required_by_field_name()
        assert required["key_file"] is True
        assert required["metric_filter"] is True

    def test_aggregation_settings_are_optional(self):
        required = _required_by_field_name()
        for name in ("per_series_aligner", "alignment_period_seconds", "cross_series_reducer", "group_by_fields"):
            assert required[name] is False

    def test_retargeting_the_project_re_requires_the_key(self):
        assert GcpCloudMonitoringSource().connection_host_fields == ["project_id"]

    def test_table_catalog_is_published_without_credentials(self):
        assert GcpCloudMonitoringSource.lists_tables_without_credentials is True


class TestGetSchemas:
    def test_lists_every_declared_table(self):
        names = [schema.name for schema in GcpCloudMonitoringSource().get_schemas(_config(), team_id=1)]
        assert names == list(ENDPOINTS)

    def test_only_time_series_is_incremental(self):
        schemas = {s.name: s for s in GcpCloudMonitoringSource().get_schemas(_config(), team_id=1)}
        assert schemas[TIME_SERIES].supports_incremental is True
        assert schemas["MetricDescriptors"].supports_incremental is False
        assert schemas["MonitoredResourceDescriptors"].supports_incremental is False

    def test_time_series_tracks_the_interval_end(self):
        schemas = {s.name: s for s in GcpCloudMonitoringSource().get_schemas(_config(), team_id=1)}
        assert [f["field"] for f in schemas[TIME_SERIES].incremental_fields] == ["point_end_time"]

    def test_time_series_re_reads_a_trailing_window_for_late_points(self):
        schemas = {s.name: s for s in GcpCloudMonitoringSource().get_schemas(_config(), team_id=1)}
        assert schemas[TIME_SERIES].default_incremental_lookback_seconds == INCREMENTAL_LOOKBACK_SECONDS

    def test_get_schemas_makes_no_network_call(self):
        with patch(f"{SOURCE_MODULE}.make_authed_session") as session:
            GcpCloudMonitoringSource().get_schemas(_config(), team_id=1)
        session.assert_not_called()


class TestProjectResolution:
    def test_the_key_files_project_is_used_when_none_is_given(self):
        with patch(f"{SOURCE_MODULE}.make_authed_session") as session:
            GcpCloudMonitoringSource().validate_credentials(_config(), team_id=1)
        assert session.call_args.kwargs["project_id"] == "key-project"

    def test_an_explicit_project_overrides_the_key_file(self):
        with patch(f"{SOURCE_MODULE}.make_authed_session") as session:
            GcpCloudMonitoringSource().validate_credentials(_config(project_id="other"), team_id=1)
        assert session.call_args.kwargs["project_id"] == "other"


class TestValidateCredentials:
    def test_delegates_to_the_transport_validator(self):
        with (
            patch(f"{SOURCE_MODULE}.make_authed_session"),
            patch(f"{SOURCE_MODULE}.validate_monitoring_credentials", return_value=(True, None)) as validate,
        ):
            assert GcpCloudMonitoringSource().validate_credentials(_config(), team_id=1) == (True, None)
        assert validate.call_args.args[1] == "key-project"

    def test_the_uploaded_token_uri_is_never_used(self):
        with patch(f"{SOURCE_MODULE}.make_authed_session") as session:
            GcpCloudMonitoringSource().validate_credentials(_config(), team_id=1)
        assert "token_uri" not in session.call_args.kwargs

    @pytest.mark.parametrize(
        "overrides",
        [
            {"cross_series_reducer": "REDUCE_SUM"},
            {"group_by_fields": "resource.labels.service"},
            {"alignment_period_seconds": 300},
            {"per_series_aligner": "ALIGN_SUM", "group_by_fields": "resource.labels.service"},
        ],
    )
    def test_aggregation_that_would_be_ignored_is_rejected_before_any_network_call(self, overrides):
        with patch(f"{SOURCE_MODULE}.make_authed_session") as session:
            ok, message = GcpCloudMonitoringSource().validate_credentials(_config(**overrides), team_id=1)
        assert ok is False
        assert message is not None and ("aligner" in message or "reducer" in message)
        session.assert_not_called()

    def test_an_unreadable_key_file_reports_that_rather_than_raising(self):
        with patch(f"{SOURCE_MODULE}.make_authed_session", side_effect=ValueError("bad key")):
            ok, message = GcpCloudMonitoringSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert message is not None and "key file" in message


class TestResumableWiring:
    def test_manager_is_bound_to_the_resume_dataclass(self):
        manager = GcpCloudMonitoringSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GcpCloudMonitoringResumeConfig


class TestSourceForPipeline:
    def _response(self, schema_name: str, config=None, **input_overrides):
        with patch(f"{SOURCE_MODULE}.make_authed_session"):
            return GcpCloudMonitoringSource().source_for_pipeline(
                config or _config(), MagicMock(), _inputs(schema_name, **input_overrides)
            )

    @pytest.mark.parametrize("schema_name", list(ENDPOINTS))
    def test_every_table_declares_its_primary_key(self, schema_name: str):
        response = self._response(schema_name)
        assert response.name == schema_name
        assert response.primary_keys == PRIMARY_KEYS[schema_name]

    def test_the_time_series_key_identifies_a_series_and_an_interval(self):
        assert PRIMARY_KEYS[TIME_SERIES] == ["series_key", "point_end_time"]

    def test_time_series_partitions_by_the_stable_interval_end(self):
        response = self._response(TIME_SERIES)
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["point_end_time"]

    def test_descriptor_tables_are_not_partitioned(self):
        response = self._response("MetricDescriptors")
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_sort_mode_matches_the_ascending_sort_the_transport_applies(self):
        assert self._response(TIME_SERIES).sort_mode == "asc"

    def test_the_session_is_built_when_the_sync_runs_not_when_the_response_is_assembled(self):
        with patch(f"{SOURCE_MODULE}.make_authed_session") as session:
            response = GcpCloudMonitoringSource().source_for_pipeline(_config(), MagicMock(), _inputs())
            session.assert_not_called()
            with patch(f"{SOURCE_MODULE}.gcp_cloud_monitoring_source"):
                response.items()
        session.assert_called_once()

    def test_full_refresh_run_passes_no_cursor(self):
        with (
            patch(f"{SOURCE_MODULE}.make_authed_session"),
            patch(f"{SOURCE_MODULE}.gcp_cloud_monitoring_source") as transport,
        ):
            self._response(TIME_SERIES, should_use_incremental_field=False).items()
        assert transport.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_group_by_fields_are_split_and_trimmed(self):
        config = _config(group_by_fields=" resource.labels.service , metric.labels.method ")
        with (
            patch(f"{SOURCE_MODULE}.make_authed_session"),
            patch(f"{SOURCE_MODULE}.gcp_cloud_monitoring_source") as transport,
        ):
            self._response(TIME_SERIES, config=config).items()
        assert transport.call_args.kwargs["group_by_fields"] == [
            "resource.labels.service",
            "metric.labels.method",
        ]

    def test_blank_aggregation_settings_reach_the_transport_as_none(self):
        with (
            patch(f"{SOURCE_MODULE}.make_authed_session"),
            patch(f"{SOURCE_MODULE}.gcp_cloud_monitoring_source") as transport,
        ):
            self._response(TIME_SERIES).items()
        assert transport.call_args.kwargs["per_series_aligner"] is None
        assert transport.call_args.kwargs["cross_series_reducer"] is None
        assert transport.call_args.kwargs["group_by_fields"] is None


class TestNonRetryableErrors:
    def test_auth_and_permission_failures_stop_retrying(self):
        errors = GcpCloudMonitoringSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestCanonicalDescriptions:
    def test_every_table_is_documented(self):
        descriptions = GcpCloudMonitoringSource().get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

    def test_primary_key_columns_are_documented(self):
        descriptions = GcpCloudMonitoringSource().get_canonical_descriptions()
        for name in ENDPOINTS:
            for key in PRIMARY_KEYS[name]:
                assert key in descriptions[name]["columns"], f"{name} key column {key} is undocumented"
