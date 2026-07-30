import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.datahub import DatahubResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source import DatahubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DatahubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDatahubSource:
    def setup_method(self) -> None:
        self.source = DatahubSource()
        self.team_id = 123
        self.config = DatahubSourceConfig(instance_url="https://datahub.example.com", api_token="secret-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DATAHUB

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Datahub"
        assert config.label == "DataHub"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/datahub"
        # A finished source must be visible in the wizard — the scaffold-era hidden flag stays out.
        assert not config.unreleasedSource

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["instance_url", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_connection_host_fields_covers_instance_url(self) -> None:
        # The stored access token is sent to whatever `instance_url` points at, so retargeting
        # the URL must force the editor to re-enter the token.
        assert self.source.connection_host_fields == ["instance_url"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["datasets"])
        assert len(schemas) == 1
        assert schemas[0].name == "datasets"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://datahub.example.com/openapi/v3/entity/dataset",),
            ("403 Client Error: Forbidden for url: https://datahub.example.com/openapi/v3/entity/corpuser",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://datahub.example.com/openapi/v3/entity/dataset",),
            ("429 Client Error: Too Many Requests for url: https://datahub.example.com/openapi/v3/entity/tag",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.validate_datahub_credentials"
    )
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid DataHub access token")
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="datasets")
        assert result == (False, "Invalid DataHub access token")
        mock_validate.assert_called_once_with("https://datahub.example.com", "secret-token", "datasets", self.team_id)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates_to_shared_helper(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"users": "needs view privilege", "datasets": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["users", "datasets"])
        assert result == {"users": "needs view privilege", "datasets": None}
        mock_check.assert_called_once_with(
            "https://datahub.example.com", "secret-token", ["users", "datasets"], self.team_id
        )

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DatahubResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.datahub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "datasets"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://datahub.example.com"
        assert kwargs["api_token"] == "secret-token"
        assert kwargs["endpoint"] == "datasets"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown DataHub schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
