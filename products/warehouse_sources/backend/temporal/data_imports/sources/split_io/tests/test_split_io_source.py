import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SplitIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.source import SplitIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.split_io.split_io import SplitIoResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSplitIoSource:
    def setup_method(self):
        self.source = SplitIoSource()
        self.team_id = 123
        self.config = SplitIoSourceConfig(api_key="admin-api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SPLITIO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "SplitIo"
        assert config.label == "Split.io"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/split_io.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.split.io/internal/api/v2/workspaces",
            "403 Client Error: Forbidden for url: https://api.split.io/internal/api/v2/splits/ws/abc",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        observed_error = "500 Server Error for url: https://api.split.io/internal/api/v2/workspaces"
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_all_endpoints_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # The Split Admin API has no server-side timestamp filter, so nothing is incremental.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["feature_flags"])
        assert len(schemas) == 1
        assert schemas[0].name == "feature_flags"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A valid key may lack scope for an unselected endpoint — accept 403 at source-create.
            (403, None, True),
            # But reject 403 when validating a specific schema.
            (403, "feature_flags", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.split_io.source.validate_split_io_credentials"
    )
    def test_validate_credentials_status_mapping(self, mock_validate, status, schema_name, expected_valid):
        mock_validate.return_value = status

        is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid

    def test_validate_credentials_unknown_schema_rejected_without_probe(self):
        is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name="nope")
        assert is_valid is False
        assert error is not None and "nope" in error

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SplitIoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.split_io.source.split_io_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_split_io_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "workspaces"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_split_io_source.call_args.kwargs
        assert kwargs["api_key"] == "admin-api-key"
        assert kwargs["endpoint"] == "workspaces"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"

        with pytest.raises(ValueError, match="Unknown Split schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
