import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UptimerobotSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.settings import (
    ENDPOINTS,
    UPTIMEROBOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.source import UptimerobotSource
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.uptimerobot import (
    UptimeRobotResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"monitor_logs", "response_times"}
_FULL_REFRESH_ENDPOINTS = {"monitors", "alert_contacts", "maintenance_windows", "status_pages"}


class TestUptimerobotSource:
    def setup_method(self):
        self.source = UptimerobotSource()
        self.team_id = 123
        self.config = UptimerobotSourceConfig(api_key="ur123-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.UPTIMEROBOT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Uptimerobot"
        assert config.label == "UptimeRobot"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/uptimerobot.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/uptimerobot"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_non_retryable_errors_match_transport_auth_failure(self):
        # UptimeRobot signals a bad key in-body over HTTP 200; the transport raises with this message.
        observed_error = "UptimeRobot API key was rejected: api_key is invalid."
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "UptimeRobot API error (retryable): status=429, method=getMonitors",
            "UptimeRobot API error (invalid_parameter): offset is invalid.",
            "HTTPSConnectionPool(host='api.uptimerobot.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["datetime"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(UPTIMEROBOT_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid UptimeRobot API key"), False, "Invalid UptimeRobot API key"),
            ((False, "Could not connect to UptimeRobot"), False, "Could not connect to UptimeRobot"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.source.validate_uptimerobot_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("ur123-key")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is UptimeRobotResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.source.uptimerobot_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_uptimerobot_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "monitor_logs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1750000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_uptimerobot_source.assert_called_once()
        kwargs = mock_uptimerobot_source.call_args.kwargs
        assert kwargs["api_key"] == "ur123-key"
        assert kwargs["endpoint"] == "monitor_logs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == 1750000000

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.source.uptimerobot_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_uptimerobot_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "monitors"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1750000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_uptimerobot_source.call_args.kwargs["db_incremental_field_last_value"] is None
