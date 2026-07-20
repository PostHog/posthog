import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    JamfProAuthMethodConfig,
    JamfProSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.jamf_pro import JamfProResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source import JamfProSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestJamfProSource:
    def setup_method(self):
        self.source = JamfProSource()
        self.team_id = 123
        self.config = JamfProSourceConfig(
            instance_url="example.jamfcloud.com",
            auth_method=JamfProAuthMethodConfig(
                selection="client_credentials", client_id="cid", client_secret="secret"
            ),
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.JAMFPRO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "JamfPro"
        assert config.label == "Jamf Pro"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

        field_names = [f.name for f in config.fields]
        assert field_names == ["instance_url", "auth_method"]

        url_field, auth_field = config.fields
        assert isinstance(url_field, SourceFieldInputConfig)
        assert url_field.secret is False
        assert url_field.required is True

        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert [option.value for option in auth_field.options] == ["client_credentials", "basic"]
        secret_flags = {
            f.name: f.secret for option in auth_field.options for f in option.fields or [] if hasattr(f, "secret")
        }
        assert secret_flags == {"client_id": False, "client_secret": True, "username": False, "password": True}

    def test_connection_host_fields_covers_instance_url(self):
        # Without this, an org member could retarget the instance URL at a server they control
        # and exfiltrate the preserved credentials.
        assert self.source.connection_host_fields == ["instance_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_schema_sync_modes(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        # Only computer inventory documents a server-side RSQL timestamp filter; everything else
        # is full-refresh. Inventory records mutate in place, so append mode is never offered.
        assert schemas[endpoint].supports_incremental is (endpoint == "computers")
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["computers"])
        assert [s.name for s in schemas] == ["computers"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source.validate_jamf_pro_credentials"
    )
    def test_validate_credentials_maps_client_credentials(self, mock_validate):
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="computers")

        assert result == (True, None)
        args = mock_validate.call_args.args
        assert args[0] == "example.jamfcloud.com"
        credentials = args[1]
        assert credentials.method == "client_credentials"
        assert credentials.client_id == "cid"
        assert credentials.client_secret == "secret"
        assert args[2] == "computers"
        assert args[3] == self.team_id

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source.validate_jamf_pro_credentials"
    )
    def test_validate_credentials_maps_basic_auth(self, mock_validate):
        mock_validate.return_value = (True, None)
        config = JamfProSourceConfig(
            instance_url="example.jamfcloud.com",
            auth_method=JamfProAuthMethodConfig(selection="basic", username="admin", password="pw"),
        )

        self.source.validate_credentials(config, self.team_id)

        credentials = mock_validate.call_args.args[1]
        assert credentials.method == "basic"
        assert credentials.username == "admin"
        assert credentials.password == "pw"

    def test_get_resumable_source_manager(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JamfProResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source.jamf_pro_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_jamf_pro_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "computers"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_jamf_pro_source.call_args.kwargs
        assert kwargs["host"] == "example.jamfcloud.com"
        assert kwargs["credentials"].client_id == "cid"
        assert kwargs["endpoint"] == "computers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source.jamf_pro_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_jamf_pro_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "buildings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_jamf_pro_source.call_args.kwargs["db_incremental_field_last_value"] is None
