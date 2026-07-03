import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StatuspageSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.source import StatuspageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.statuspage import (
    StatuspageResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestStatuspageSource:
    def setup_method(self):
        self.source = StatuspageSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.STATUSPAGE

    def test_source_config(self):
        config = self.source.get_source_config
        assert config.label == "Statuspage"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True

    def test_source_config_has_secret_api_key_field(self):
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

    def test_get_schemas_returns_all_endpoints_as_full_refresh(self):
        schemas = self.source.get_schemas(StatuspageSourceConfig(api_key="key"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No server-side timestamp filter exists, so every schema is full-refresh only.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(
            StatuspageSourceConfig(api_key="key"), self.team_id, names=["incidents", "components"]
        )
        assert {s.name for s in schemas} == {"incidents", "components"}

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Could not authenticate"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.source.validate_statuspage_credentials"
    )
    def test_validate_credentials_delegates_with_api_key(self, mock_validate):
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(StatuspageSourceConfig(api_key="secret-key"), self.team_id)
        assert result == (True, None)
        mock_validate.assert_called_once_with("secret-key")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is StatuspageResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.source.statuspage_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_statuspage_source):
        config = StatuspageSourceConfig(api_key="key")
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "incidents"
        inputs.logger = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        mock_statuspage_source.assert_called_once_with(
            api_key="key",
            endpoint="incidents",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
