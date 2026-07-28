import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.dovetail import DovetailResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.source import DovetailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dovetail import (
    DovetailSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDovetailSource:
    def setup_method(self) -> None:
        self.source = DovetailSource()
        self.team_id = 123
        self.config = DovetailSourceConfig(api_key="dovetail-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DOVETAIL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Dovetail"
        assert config.label == "Dovetail"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/dovetail.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dovetail"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_endpoints(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in ("Data", "Docs", "Highlights"):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["created_at"]

        for name in ("Projects", "Tags", "Contacts", "Users", "DocComments"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Data"])
        assert len(schemas) == 1
        assert schemas[0].name == "Data"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://dovetail.com/api/v1/data",
            "403 Client Error: Forbidden for url: https://dovetail.com/api/v1/data",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in "500 Server Error for url: https://dovetail.com/api/v1/data" for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.source.validate_dovetail_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="Data")

        assert result == (True, None)
        mock_validate.assert_called_once_with("dovetail-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DovetailResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.source.dovetail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_dovetail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Data"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_dovetail_source.call_args.kwargs
        assert kwargs["api_key"] == "dovetail-key"
        assert kwargs["endpoint"] == "Data"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "created_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.source.dovetail_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_dovetail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Projects"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_dovetail_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
