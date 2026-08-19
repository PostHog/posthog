import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vendr import VendrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.settings import ENDPOINTS, VENDR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.source import VendrSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr import VendrResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestVendrSource:
    def setup_method(self) -> None:
        self.source = VendrSource()
        self.team_id = 123
        self.config = VendrSourceConfig(api_key="vendr-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.VENDR

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Vendr"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/vendr.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # Every endpoint is a static entry in ENDPOINTS with no I/O - safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # Vendr's catalog API documents no updated-since/created-since filter on any endpoint.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_expose_primary_keys(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        for name in ENDPOINTS:
            assert schemas[name].detected_primary_keys == VENDR_ENDPOINTS[name].primary_keys

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Companies"])
        assert [schema.name for schema in schemas] == ["Companies"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["Nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        companies = next(t for t in tables if t["name"] == "Companies")
        assert companies["sync_methods"] == ["Full refresh"]
        assert companies["primary_keys"] == ["id"]
        assert companies["description"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.vendr.com/v1/catalog/companies?limit=100",
            "403 Client Error: Forbidden for url: https://api.vendr.com/v1/catalog/categories?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.vendr.com/v1/catalog/companies",
            "500 Server Error: Internal Server Error for url: https://api.vendr.com/v1/catalog/companies",
            "HTTPSConnectionPool(host='api.vendr.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ((True, None), True, None),
            ((False, 401), False, "Invalid Vendr API key"),
            ((False, 403), False, "Invalid Vendr API key"),
            ((False, None), False, "Invalid Vendr API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vendr.source.validate_vendr_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("vendr-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is VendrResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.vendr.source.vendr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_vendr_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Products"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_vendr_source.assert_called_once()
        kwargs = mock_vendr_source.call_args.kwargs
        assert kwargs["api_key"] == "vendr-key"
        assert kwargs["endpoint"] == "Products"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(VENDR_ENDPOINTS.keys())
