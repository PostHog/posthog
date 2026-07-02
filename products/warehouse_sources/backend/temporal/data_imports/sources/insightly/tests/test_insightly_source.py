import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InsightlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly import InsightlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import (
    ENDPOINTS,
    INSIGHTLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source import InsightlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Derived from settings so a new endpoint is automatically covered by the parametrized tests below.
INCREMENTAL_ENDPOINTS = {name for name, cfg in INSIGHTLY_ENDPOINTS.items() if cfg.supports_incremental}
FULL_REFRESH_ENDPOINTS = {name for name, cfg in INSIGHTLY_ENDPOINTS.items() if not cfg.supports_incremental}


class TestInsightlySource:
    def setup_method(self) -> None:
        self.source = InsightlySource()
        self.team_id = 123
        self.config = InsightlySourceConfig(pod="na1", api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.INSIGHTLY

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Insightly"
        assert config.label == "Insightly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/insightly"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["pod", "api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_pod_is_connection_host_field(self) -> None:
        assert self.source.connection_host_fields == ["pod"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.na1.insightly.com/v3.1/Contacts?top=500&skip=0",
            "403 Client Error: Forbidden for url: https://api.na1.insightly.com/v3.1/Leads?top=500&skip=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.na1.insightly.com/v3.1/Contacts",
            "500 Server Error for url: https://api.na1.insightly.com/v3.1/Notes",
        ],
    )
    def test_transient_errors_are_not_marked_non_retryable(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(INCREMENTAL_ENDPOINTS))
    def test_incremental_endpoints_advertise_updated_at_cursor(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id, names=[endpoint]))
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["DATE_UPDATED_UTC"]

    @pytest.mark.parametrize("endpoint", sorted(FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoints_have_no_incremental(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id, names=[endpoint]))
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Contacts"])
        assert [s.name for s in schemas] == ["Contacts"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "status, schema_name, expected_ok",
        [
            (200, None, True),
            (200, "Contacts", True),
            (403, None, True),  # missing scope tolerated at source-create
            (403, "Leads", False),  # but rejected for a specific schema
            (401, None, False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source.validate_insightly_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        mock_validate.return_value = status
        ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name)
        assert ok is expected_ok

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source.validate_insightly_credentials"
    )
    def test_validate_credentials_rejects_invalid_pod(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = ValueError("Invalid Insightly pod/instance: 'evil.com'")
        ok, message = self.source.validate_credentials(
            InsightlySourceConfig(pod="evil.com", api_key="key"), self.team_id
        )
        assert ok is False
        assert "Invalid Insightly pod" in (message or "")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is InsightlyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source.insightly_source")
    def test_source_for_pipeline_passes_normalized_pod_and_cursor(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Contacts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2020-01-01T00:00:00Z"
        manager = mock.MagicMock()

        # A full API URL in the pod field is normalized to the bare pod token.
        self.source.source_for_pipeline(
            InsightlySourceConfig(pod="https://api.eu1.insightly.com/v3.1", api_key="key"), manager, inputs
        )

        kwargs = mock_source.call_args.kwargs
        assert kwargs["pod"] == "eu1"
        assert kwargs["endpoint"] == "Contacts"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2020-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source.insightly_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Contacts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2020-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
