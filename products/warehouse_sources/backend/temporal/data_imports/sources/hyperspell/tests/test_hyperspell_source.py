import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HyperspellSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source import HyperspellSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHyperspellSource:
    def setup_method(self):
        self.source = HyperspellSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HYPERSPELL

    def test_source_config(self):
        config = self.source.get_source_config
        assert config.label == "Hyperspell"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hyperspell"

    def test_source_config_fields(self):
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_key", "region", "user_id"]

        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True

        # API keys are region-locked, so the region select must exist and default to US.
        region = fields[1]
        assert isinstance(region, SourceFieldSelectConfig)
        assert region.defaultValue == "us"
        assert {o.value for o in region.options} == {"us", "eu"}

        user_id = fields[2]
        assert isinstance(user_id, SourceFieldInputConfig)
        assert user_id.required is False
        assert user_id.secret is False

    def test_connection_host_fields_cover_region_and_user(self):
        # region picks the host the key is sent to and user_id sets the X-As-User identity, so
        # changing either must force the secret to be re-entered rather than reusing the stored key.
        assert self.source.connection_host_fields == ["region", "user_id"]

    def test_get_schemas_returns_all_endpoints_as_full_refresh(self):
        schemas = self.source.get_schemas(HyperspellSourceConfig(api_key="key"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No server-side timestamp filter exists, so every schema is full-refresh only.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(
            HyperspellSourceConfig(api_key="key"), self.team_id, names=["memories", "connections"]
        )
        assert {s.name for s in schemas} == {"memories", "connections"}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — the docs Supported tables section renders from it.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source.validate_hyperspell_credentials"
    )
    def test_validate_credentials_delegates_config_values(self, mock_validate):
        mock_validate.return_value = (True, None)
        config = HyperspellSourceConfig(api_key="secret-key", region="eu", user_id="user-1")
        result = self.source.validate_credentials(config, self.team_id)
        assert result == (True, None)
        mock_validate.assert_called_once_with("secret-key", "eu", "user-1")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HyperspellResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source.hyperspell_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hyperspell_source):
        config = HyperspellSourceConfig(api_key="key", region="us", user_id=None)
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "memories"
        inputs.logger = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        mock_hyperspell_source.assert_called_once_with(
            api_key="key",
            region="us",
            user_id=None,
            endpoint="memories",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
