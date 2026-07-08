import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import CalendlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source import CalendlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CalendlySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "scheduled_events", **overrides):
    defaults = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
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
    return mock.MagicMock(**defaults)


class TestCalendlySource:
    def setup_method(self):
        self.source = CalendlySource()
        self.team_id = 123
        self.config = CalendlySourceConfig(personal_access_token="cal_test_token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CALENDLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Calendly"
        assert config.label == "Calendly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is not True
        assert config.iconPath == "/static/services/calendly.png"
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "personal_access_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.calendly.com",
            "403 Client Error: Forbidden for url: https://api.calendly.com",
        ],
    )
    def test_non_retryable_errors_includes_calendly_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://api.calendly.com/scheduled_events?count=100"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.klaviyo.com/api/accounts",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

        by_name = {schema.name: schema for schema in schemas}
        # Only scheduled_events has a genuine server-side time filter.
        assert by_name["scheduled_events"].supports_incremental is True
        assert by_name["scheduled_events"].supports_append is True
        assert {f["field"] for f in by_name["scheduled_events"].incremental_fields} == {"start_time"}

        for name in ("event_types", "groups", "organization_memberships", "routing_forms"):
            assert by_name[name].supports_incremental is False
            assert by_name[name].supports_append is False
            assert by_name[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["scheduled_events"])

        assert len(schemas) == 1
        assert schemas[0].name == "scheduled_events"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Calendly personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.validate_calendly_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CalendlyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.calendly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_calendly_source):
        inputs = _make_inputs(
            schema_name="scheduled_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000000Z",
        )
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_calendly_source.assert_called_once()
        kwargs = mock_calendly_source.call_args.kwargs
        assert kwargs["token"] == "cal_test_token"
        assert kwargs["endpoint"] == "scheduled_events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.calendly.source.calendly_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_calendly_source):
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000000Z",
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_calendly_source.call_args.kwargs["db_incremental_field_last_value"] is None
