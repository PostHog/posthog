from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.northpasslms import (
    NorthpassLMSSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.source import NorthpassLMSSource


class TestNorthpassLMSSource:
    def setup_method(self):
        self.source = NorthpassLMSSource()
        self.team_id = 123
        self.config = NorthpassLMSSourceConfig(api_key="key")

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "NorthpassLMS"
        assert config.label == "Northpass LMS"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — the scaffold's unreleasedSource flag must be gone.
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/northpass_lms.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/northpass-lms"

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.northpass.com/v2/people?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.northpass.com/v2/courses?limit=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("throttle", "429 Client Error: Too Many Requests for url: https://api.northpass.com/v2/people"),
            ("server", "500 Server Error: Internal Server Error for url: https://api.northpass.com/v2/people"),
            ("timeout", "HTTPSConnectionPool(host='api.northpass.com', port=443): Read timed out."),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, _name, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_all_full_refresh(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Northpass documents no server-side timestamp filter, so nothing may advertise incremental.
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_expose_endpoint_primary_keys(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Fan-out children must carry the parent id in their key so rows stay unique table-wide.
        assert schemas["people"].detected_primary_keys == ["id"]
        assert schemas["course_enrollments"].detected_primary_keys == ["course_id", "id"]
        assert schemas["learning_path_enrollments"].detected_primary_keys == ["learning_path_id", "id"]
        assert schemas["course_activities"].detected_primary_keys == ["course_id", "id"]
        # Events carry no id of their own, so the key is the full (who, what, when) grain.
        assert schemas["activity_events"].detected_primary_keys == ["person_id", "activity_id", "type", "created_at"]
        assert schemas["quiz_attempts"].detected_primary_keys == ["id"]
        assert schemas["quiz_attempt_answers"].detected_primary_keys == ["quiz_attempt_id", "id"]

    def test_costly_schemas_are_off_by_default(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        # The event stream re-fetches its full history every sync, and both quiz tables depend on
        # the sent-webhooks log (subscription required, three-month retention) with a per-attempt
        # fan-out, so connecting the source must not silently enable them; everything else keeps
        # syncing by default.
        off_by_default = {schema.name for schema in schemas if not schema.should_sync_default}
        assert off_by_default == {"activity_events", "quiz_attempts", "quiz_attempt_answers"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["courses"])
        assert len(schemas) == 1
        assert schemas[0].name == "courses"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("valid", (True, 200), True, None),
            ("unauthorized", (False, 401), False, "Invalid Northpass API key"),
            ("forbidden", (False, 403), False, "Invalid Northpass API key"),
            (
                "transport_error",
                (False, None),
                False,
                "Could not connect to Northpass. Please check your API key and try again.",
            ),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.source.validate_northpass_credentials"
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
