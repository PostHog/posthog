import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PretixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.pretix import PretixResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source import PretixSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPretixSource:
    def setup_method(self):
        self.source = PretixSource()
        self.team_id = 123
        self.config = PretixSourceConfig(organizer="acme", api_token="test-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PRETIX

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Pretix"
        assert config.label == "Pretix"
        assert config.releaseStatus == "alpha"
        assert config.iconPath == "/static/services/pretix.png"

        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"organizer", "api_token", "base_url"}

        token_field = fields["api_token"]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

        organizer_field = fields["organizer"]
        assert isinstance(organizer_field, SourceFieldInputConfig)
        assert organizer_field.required is True

        base_url_field = fields["base_url"]
        assert isinstance(base_url_field, SourceFieldInputConfig)
        assert base_url_field.required is False

    def test_connection_host_fields_covers_base_url(self):
        # Retargeting the API URL must force re-entry of the token, otherwise an editor could point
        # the preserved token at a host they control.
        assert self.source.connection_host_fields == ["base_url"]

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://pretix.eu/api/v1/organizers/acme/orders/"
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

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

    def test_orders_is_the_only_incremental_endpoint(self):
        # Only `orders` has a documented server-side `modified_since` filter; advertising incremental
        # on another endpoint would silently full-refresh under an incremental label.
        assert set(INCREMENTAL_ENDPOINTS) == {"orders"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events", "nonexistent"])

        assert [schema.name for schema in schemas] == ["events"]

    @parameterized.expand(
        [
            ((True, None),),
            ((False, "Invalid pretix API token"),),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source.validate_pretix_credentials"
    )
    def test_validate_credentials_delegates_to_transport(self, validation_result, mock_validate):
        mock_validate.return_value = validation_result

        assert self.source.validate_credentials(self.config, self.team_id) == validation_result
        mock_validate.assert_called_once_with(
            self.config.api_token, self.config.organizer, self.config.base_url, self.team_id
        )

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        inputs.logger = mock.MagicMock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert manager._data_class is PretixResumeConfig

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "nonexistent"

        with pytest.raises(ValueError, match="Unknown pretix schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source.pretix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pretix_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = self.team_id
        inputs.logger = mock.MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "last_modified"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pretix_source.assert_called_once_with(
            api_token=self.config.api_token,
            organizer=self.config.organizer,
            base_url=self.config.base_url,
            endpoint="orders",
            team_id=self.team_id,
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="last_modified",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pretix.source.pretix_source")
    def test_source_for_pipeline_nulls_last_value_when_not_incremental(self, mock_pretix_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.team_id = self.team_id
        inputs.logger = mock.MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_pretix_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["should_use_incremental_field"] is False
