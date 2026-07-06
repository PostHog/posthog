import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LatticeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice import LatticeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.source import LatticeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLatticeSource:
    def setup_method(self):
        self.source = LatticeSource()
        self.team_id = 123
        self.config = LatticeSourceConfig(region="us", api_key="api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LATTICE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Lattice"
        assert config.label == "Lattice"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/lattice.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["region", "api_key"]

    def test_region_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "emea"}

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.latticehq.com/v1/users?limit=100",
            "401 Client Error: Unauthorized for url: https://api.emea.latticehq.com/v1/goals",
            "403 Client Error: Forbidden for url: https://api.latticehq.com/v1/feedbacks",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.latticehq.com/v1/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Lattice list endpoint has a server-side timestamp filter.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Lattice API key"),
            (False, "Could not reach Lattice: boom"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lattice.source.validate_lattice_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == mock_return
        mock_validate.assert_called_once_with("us", "api-key")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LatticeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.source.lattice_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_lattice_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_lattice_source.assert_called_once()
        kwargs = mock_lattice_source.call_args.kwargs
        assert kwargs["region"] == "us"
        assert kwargs["api_key"] == "api-key"
        assert kwargs["endpoint"] == "users"
        assert kwargs["resumable_source_manager"] is manager
