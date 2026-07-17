import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IncidentIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source import IncidentIoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestIncidentIoSource:
    def setup_method(self):
        self.source = IncidentIoSource()
        self.team_id = 123
        self.config = IncidentIoSourceConfig(api_key="api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.INCIDENTIO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "IncidentIo"
        assert config.label == "incident.io"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/incident_io.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.incident.io/v2/incidents?page_size=250",
            "403 Client Error: Forbidden for url: https://api.incident.io/v2/alerts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.incident.io/v2/incidents",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the incidents list exposes server-side timestamp filters with a sortable order.
        assert incremental == {"incidents"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["incidents"].incremental_fields == INCREMENTAL_FIELDS["incidents"]
        assert {f["field"] for f in schemas["incidents"].incremental_fields} == {"created_at", "updated_at"}

    @pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e != "incidents"])
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["incidents"])
        assert len(schemas) == 1
        assert schemas[0].name == "incidents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "schema_name, mock_return",
        [
            (None, (True, None)),
            (None, (False, "incident.io authentication failed. Please check that your API key is valid.")),
            ("alerts", (False, "Your incident.io API key can't list alerts.")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source.validate_incident_io_credentials"
    )
    def test_validate_credentials_passthrough(self, mock_validate, schema_name, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert result == mock_return
        mock_validate.assert_called_once_with(self.config.api_key, schema_name)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is IncidentIoResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source.incident_io_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_incident_io_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "incidents"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        inputs.incremental_field = "updated_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_incident_io_source.assert_called_once()
        kwargs = mock_incident_io_source.call_args.kwargs
        assert kwargs["api_key"] == "api-key"
        assert kwargs["endpoint"] == "incidents"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source.incident_io_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_incident_io_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "severities"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_incident_io_source.call_args.kwargs["db_incremental_field_last_value"] is None
