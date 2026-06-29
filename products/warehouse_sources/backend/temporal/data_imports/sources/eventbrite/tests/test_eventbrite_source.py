import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.eventbrite import (
    EventbriteResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source import EventbriteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EventbriteSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestEventbriteSource:
    def setup_method(self):
        self.source = EventbriteSource()
        self.team_id = 123
        self.config = EventbriteSourceConfig(api_token="test-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.EVENTBRITE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Eventbrite"
        assert config.label == "Eventbrite"
        assert config.releaseStatus == "alpha"
        assert config.iconPath == "/static/services/eventbrite.png"
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://www.eventbriteapi.com",
            "403 Client Error: Forbidden for url: https://www.eventbriteapi.com",
        ],
    )
    def test_non_retryable_errors_includes_eventbrite_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = (
            "401 Client Error: Unauthorized for url: https://www.eventbriteapi.com/v3/users/me/organizations/"
        )
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://a.klaviyo.com/api/accounts",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags_match_settings(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        for schema in schemas:
            expected = schema.name in INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected
            if expected:
                assert schema.incremental_fields, f"{schema.name} should advertise incremental fields"
            else:
                assert schema.incremental_fields == []

    def test_get_schemas_incremental_endpoints_are_orders_and_attendees(self):
        assert set(INCREMENTAL_ENDPOINTS) == {"orders", "attendees"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events"])

        assert len(schemas) == 1
        assert schemas[0].name == "events"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @pytest.mark.parametrize(
        "credentials_valid, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Eventbrite private token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source.validate_eventbrite_credentials"
    )
    def test_validate_credentials(self, mock_validate, credentials_valid, expected_valid, expected_message):
        mock_validate.return_value = credentials_valid

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        inputs.logger = mock.MagicMock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert manager._data_class is EventbriteResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source.eventbrite_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_eventbrite_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.logger = mock.MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "changed"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_eventbrite_source.assert_called_once_with(
            api_token=self.config.api_token,
            endpoint="orders",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="changed",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.source.eventbrite_source")
    def test_source_for_pipeline_nulls_last_value_when_not_incremental(self, mock_eventbrite_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.logger = mock.MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_eventbrite_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["should_use_incremental_field"] is False
