import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hex import HexSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.hex import HexResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.source import HexSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHexSource:
    def setup_method(self):
        self.source = HexSource()
        self.team_id = 123
        self.config = HexSourceConfig(api_key="hex_token", workspace_url=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HEX

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Hex"
        assert config.label == "Hex"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/hex.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hex"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "workspace_url"]

        token_field, url_field = config.fields
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

        assert isinstance(url_field, SourceFieldInputConfig)
        assert url_field.type == SourceFieldInputConfigType.TEXT
        assert url_field.secret is False
        assert url_field.required is False

    def test_workspace_url_is_a_connection_host_field(self):
        # Retargeting the workspace URL must force re-entry of the API token — without this an
        # editor could point the stored token at a host they control.
        assert self.source.connection_host_fields == ["workspace_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints_full_refresh_only(self):
        # The Hex API has no server-side timestamp filter, so no endpoint may advertise
        # incremental or append sync.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["projects"])
        assert [s.name for s in schemas] == ["projects"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hex.source.validate_hex_credentials")
    def test_validate_credentials_plumbs_arguments(self, mock_validate):
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="projects")

        assert result == (True, None)
        mock_validate.assert_called_once_with(self.config.workspace_url, self.config.api_key, "projects", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HexResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hex.source.hex_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_hex_source.call_args.kwargs
        assert kwargs["api_key"] == "hex_token"
        assert kwargs["workspace_url"] is None
        assert kwargs["endpoint"] == "projects"
        assert kwargs["team_id"] == 42
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        # Full-refresh runs must not leak a stray watermark into the transport.
        assert kwargs["db_incremental_field_last_value"] is None
