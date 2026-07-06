import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GridlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.gridly import GridlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.source import GridlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gridly.source"


class TestGridlySource:
    def setup_method(self):
        self.source = GridlySource()
        self.team_id = 123
        self.config = GridlySourceConfig(api_key="key", view_id="view")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GRIDLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Gridly"
        assert config.label == "Gridly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/gridly.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "view_id"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog (no I/O), so the source opts into public-docs table listing.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.gridly.com/v1/views/abc",
            "403 Client Error: Forbidden for url: https://api.gridly.com/v1/views/abc/records",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.gridly.com/v1/views/abc/records",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)
        assert all(schema.detected_primary_keys == ["id"] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["records"])
        assert [s.name for s in schemas] == ["records"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Gridly API key. Create a new API key in your Gridly company settings, then reconnect."),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_gridly_credentials")
    def test_validate_credentials_plumbs_to_transport(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == mock_return
        mock_validate.assert_called_once_with("key", "view")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is GridlyResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.gridly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gridly_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "records"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_gridly_source.assert_called_once()
        kwargs = mock_gridly_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["view_id"] == "view"
        assert kwargs["endpoint"] == "records"
        assert kwargs["resumable_source_manager"] is manager
