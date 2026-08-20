import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko import ClinikoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source import ClinikoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cliniko import (
    ClinikoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestClinikoSource:
    def setup_method(self) -> None:
        self.source = ClinikoSource()
        self.team_id = 123
        self.config = ClinikoSourceConfig(api_key="test-key-au1")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CLINIKO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Cliniko"
        assert config.label == "Cliniko"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — no unreleasedSource flag hiding it.
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/cliniko.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cliniko"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.au1.cliniko.com/v1/patients?per_page=1",
            "403 Client Error: Forbidden for url: https://api.au1.cliniko.com/v1/patients?per_page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.au1.cliniko.com/v1/patients",
            "500 Server Error: Internal Server Error for url: https://api.au1.cliniko.com/v1/patients",
            "HTTPSConnectionPool(host='api.au1.cliniko.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_and_support_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["updated_at"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["patients"])
        assert len(schemas) == 1
        assert schemas[0].name == "patients"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self) -> None:
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source.validate_cliniko_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key-au1")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is ClinikoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source.cliniko_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cliniko_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_cliniko_source.assert_called_once()
        kwargs = mock_cliniko_source.call_args.kwargs
        assert kwargs["api_key"] == "test-key-au1"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source.cliniko_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_cliniko_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "patients"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_cliniko_source.call_args.kwargs["db_incremental_field_last_value"] is None
