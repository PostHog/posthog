import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gladly import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import (
    ENDPOINTS,
    REPORT_ENDPOINTS,
    REPORT_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source import GladlySource


class TestGladlySource:
    def setup_method(self):
        self.source = GladlySource()
        self.team_id = 123
        self.config = GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token")

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
