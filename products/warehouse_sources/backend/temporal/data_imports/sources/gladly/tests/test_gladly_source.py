import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gladly import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import GladlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import (
    ENDPOINTS,
    REPORT_ENDPOINTS,
    REPORT_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source import GladlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGladlySource:
    def setup_method(self):
        self.source = GladlySource()
        self.team_id = 123
        self.config = GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GLADLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Gladly"
        assert config.label == "Gladly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/gladly.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["organization", "agent_email", "api_token", "domain"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_connection_host_fields_cover_organization(self):
        # The org subdomain and the domain together decide where the stored token gets sent.
        assert self.source.connection_host_fields == ["organization", "domain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://myorg.gladly.com/api/v1/export/jobs",
            "403 Client Error: Forbidden for url: https://myorg.gladly.com/api/v1/export/jobs/123/files/customers.jsonl",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://myorg.gladly.com/api/v1/export/jobs"
        assert not any(key in error for key in non_retryable_errors)

    def test_retryable_errors_match_read_timeout(self):
        # response.raw streaming in _report_rows raises this bare urllib3 message when Gladly
        # stalls generating a report, uncaught by generate_report's own retry decorator.
        retryable_errors = self.source.get_retryable_errors()
        error = "HTTPSConnectionPool(host='myorg.us-1.gladly.com', port=443): Read timed out."
        assert any(key in error for key in retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.supports_incremental for schema in schemas)
        # Report windows are re-read on resume and behind the watermark, so
        # appending would duplicate rows — report streams are merge-only.
        for schema in schemas:
            assert schema.supports_append is (schema.name not in REPORT_ENDPOINTS)

    def test_schemas_advertise_the_expected_cursor(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        for schema in schemas:
            # Job-export streams cursor on the injected job watermark; report
            # streams cursor on the event's own recorded time, and the
            # conversations report on the conversation's creation timestamp.
            expected = {
                "conversations": ["created_at"],
                "conversation_timestamps": ["timestamp"],
                "contact_timestamps": ["timestamp"],
            }.get(schema.name, ["_job_updated_at"])
            assert [f["field"] for f in schema.incremental_fields] == expected

    def test_event_grain_report_schemas_start_opt_in(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        # Event-grain report tables are high-volume, so enabling them must be
        # an explicit choice; the conversations report and job-export streams
        # keep syncing by default.
        for schema in schemas:
            assert schema.should_sync_default is (schema.name not in {"conversation_timestamps", "contact_timestamps"})

    def test_conversations_schema_defaults_to_a_restatement_lookback(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        # Conversation-report rows restate in place, so only that schema
        # re-reads a trailing window on incremental runs.
        lookbacks = {schema.name: schema.default_incremental_lookback_seconds for schema in schemas}
        assert lookbacks.pop("conversations") == REPORT_INCREMENTAL_LOOKBACK_SECONDS
        assert all(seconds is None for seconds in lookbacks.values())

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "probe failure message"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.validate_gladly_credentials"
    )
    def test_validate_credentials_passes_the_probe_result_through(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_validate.assert_called_once_with("myorg", "agent@x.com", "token", "gladly.com")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GladlyResumeConfig

    @pytest.mark.parametrize("domain", ["gladly.com", "gladly.qa"])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.gladly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gladly_source, domain):
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"
        manager = mock.MagicMock()
        config = GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token", domain=domain)

        self.source.source_for_pipeline(config, manager, inputs)

        mock_gladly_source.assert_called_once()
        kwargs = mock_gladly_source.call_args.kwargs
        assert kwargs["domain"] == domain
        assert kwargs["organization"] == "myorg"
        assert kwargs["agent_email"] == "agent@x.com"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.gladly_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_gladly_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gladly_source.call_args.kwargs["db_incremental_field_last_value"] is None
