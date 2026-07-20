import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith import FlagsmithResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.source import FlagsmithSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlagsmithSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

VALIDATE_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.source.validate_flagsmith_credentials"
)


class TestFlagsmithSource:
    def setup_method(self):
        self.source = FlagsmithSource()
        self.team_id = 123
        self.config = FlagsmithSourceConfig(api_key="org-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FLAGSMITH

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Flagsmith"
        assert config.label == "Flagsmith"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/flagsmith.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/flagsmith"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "base_url"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_base_url_is_a_connection_host_field(self):
        # Retargeting the API URL must force re-entry of the API key (credential exfiltration guard).
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_lists_all_endpoints_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Flagsmith has no server-side timestamp filter, so nothing is incremental.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["features"])
        assert len(schemas) == 1
        assert schemas[0].name == "features"

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A valid key may lack scope for an unselected endpoint — accept 403 at source-create.
            (403, None, True),
            # But reject 403 when validating a specific schema.
            (403, "features", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(VALIDATE_PATH)
    def test_validate_credentials_status_mapping(self, mock_validate, status, schema_name, expected_valid):
        mock_validate.return_value = status

        is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            ("organisations", "/organisations/"),
            ("projects", "/projects/"),
            ("features", "/projects/"),
            ("feature_states", "/projects/"),
            ("audit_logs", "/organisations/"),
        ],
    )
    @mock.patch(VALIDATE_PATH)
    def test_validate_credentials_probe_paths(self, mock_validate, schema_name, expected_path):
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert mock_validate.call_args.args[2] == expected_path

    @mock.patch(VALIDATE_PATH)
    def test_validate_credentials_rejects_invalid_base_url(self, mock_validate):
        config = FlagsmithSourceConfig(api_key="org-key", base_url="https://user@evil.example.com")

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Invalid Flagsmith API URL"
        mock_validate.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.source.is_cloud")
    @mock.patch(VALIDATE_PATH)
    def test_validate_credentials_rejects_http_on_cloud(self, mock_validate, mock_is_cloud):
        mock_is_cloud.return_value = True
        config = FlagsmithSourceConfig(api_key="org-key", base_url="http://flagsmith.example.com")

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Flagsmith API URL must use https"
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FlagsmithResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.source.flagsmith_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_flagsmith_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "features"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_flagsmith_source.call_args.kwargs
        assert kwargs["api_key"] == "org-key"
        assert kwargs["base_url"] is None
        assert kwargs["endpoint"] == "features"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_invalid_base_url(self):
        config = FlagsmithSourceConfig(api_key="org-key", base_url="https://user@evil.example.com")
        inputs = mock.MagicMock()
        inputs.schema_name = "features"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Invalid Flagsmith API URL"):
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)
