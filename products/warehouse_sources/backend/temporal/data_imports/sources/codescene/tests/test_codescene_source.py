import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene import CodesceneResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.source import CodesceneSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codescene import (
    CodesceneSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCodesceneSource:
    def setup_method(self) -> None:
        self.source = CodesceneSource()
        self.team_id = 123
        self.config = CodesceneSourceConfig(api_token="cs-token", base_url=None)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CODESCENE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Codescene"
        assert config.label == "CodeScene"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/codescene.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_fields(self) -> None:
        config = self.source.get_source_config
        fields_by_name = {f.name: f for f in config.fields}
        assert set(fields_by_name) == {"api_token", "base_url"}

        api_token_field = fields_by_name["api_token"]
        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.secret is True
        assert api_token_field.required is True

        base_url_field = fields_by_name["base_url"]
        assert isinstance(base_url_field, SourceFieldInputConfig)
        assert base_url_field.required is False
        assert base_url_field.secret is False

    def test_connection_host_fields(self) -> None:
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Projects"])
        assert [s.name for s in schemas] == ["Projects"]

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("401 Client Error: Unauthorized for url: https://api.codescene.io/v2/projects", True),
            ("403 Client Error: Forbidden for url: https://api.codescene.io/v2/projects", True),
            ("500 Server Error: Internal Server Error for url: https://api.codescene.io/v2/projects", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.codescene.source.validate_codescene_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.args == ("cs-token", None, self.team_id)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is CodesceneResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.codescene.source.codescene_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_codescene_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Files"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        config = CodesceneSourceConfig(api_token="cs-token", base_url="https://codescene.example.com:3003/api/v2")
        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_codescene_source.call_args.kwargs
        assert kwargs["api_token"] == "cs-token"
        assert kwargs["base_url"] == "https://codescene.example.com:3003/api/v2"
        assert kwargs["endpoint"] == "Files"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
