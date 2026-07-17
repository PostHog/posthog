from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RailwaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.railway import RailwayResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.source import RailwaySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRailwaySource:
    def setup_method(self):
        self.source = RailwaySource()
        self.team_id = 123
        self.config = RailwaySourceConfig(api_token="railway-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RAILWAY

    def test_source_is_released(self):
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_token_field_is_secret_password(self):
        config = self.source.get_source_config

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig))
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Railway has no server-side time filters; only deployments (newest-first, watermark-stop)
        # can sync incrementally.
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"deployments"}

    def test_deployments_schema_incremental_settings(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        deployments = schemas["deployments"]
        assert [f["field"] for f in deployments.incremental_fields] == ["createdAt"]
        # Deployment rows mutate (status) — merge-only, with a lookback so recent statuses settle.
        assert deployments.supports_append is False
        assert deployments.default_incremental_lookback_seconds == 86400

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deployments", "nope"])

        assert [schema.name for schema in schemas] == ["deployments"]

    @parameterized.expand(
        [
            ((True, None), True, None),
            ((False, "Invalid Railway API token"), False, "Invalid Railway API token"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.railway.source.validate_railway_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("railway-token")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert manager._data_class is RailwayResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.railway.source.railway_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_railway_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "deployments"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_railway_source.call_args.kwargs
        assert kwargs["api_token"] == "railway-token"
        assert kwargs["endpoint"] == "deployments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.000Z"
        assert kwargs["incremental_field"] == "createdAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.railway.source.railway_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_railway_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "deployments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_railway_source.call_args.kwargs["db_incremental_field_last_value"] is None
