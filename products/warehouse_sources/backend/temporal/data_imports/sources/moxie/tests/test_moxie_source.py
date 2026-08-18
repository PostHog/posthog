import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moxie import MoxieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.source import MoxieSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestMoxieSource:
    def setup_method(self) -> None:
        self.source = MoxieSource()
        self.team_id = 123
        self.config = MoxieSourceConfig(base_url="https://pod00.withmoxie.dev/api/public", api_key="test_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.MOXIE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Moxie"
        assert config.label == "Moxie"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible to users — the scaffold's unreleasedSource flag must be gone.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/moxie.png"

    def test_fields_have_expected_types(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields.keys()) == {"base_url", "api_key"}

        assert fields["base_url"].type == SourceFieldInputConfigType.TEXT
        assert fields["base_url"].required is True
        assert fields["base_url"].secret is False

        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True

    def test_connection_host_fields(self) -> None:
        # base_url carries the API key's destination, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["clients"])
        assert [s.name for s in schemas] == ["clients"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials=True + static get_schemas means the doc's Supported tables
        # section is populated without a live connection.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_canonical_descriptions_keyed_by_endpoint_names(self) -> None:
        # A renamed endpoint would silently orphan its curated descriptions.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://pod00.withmoxie.dev/api/public/action/clients/list",
            "403 Client Error: Forbidden for url: https://pod00.withmoxie.dev/api/public/action/clients/list",
            "Moxie workspace base URL is not allowed",
            "Moxie workspace base URL must use HTTPS",
        ],
    )
    def test_non_retryable_errors_match_auth_and_host_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        ["429 Client Error: Too Many Requests", "500 Server Error", "Connection reset by peer"],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.moxie.source.validate_moxie_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (True, None)
        mock_validate.assert_called_once_with(self.config.base_url, self.config.api_key, self.team_id)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.moxie.source.moxie_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_moxie_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"

        self.source.source_for_pipeline(self.config, inputs)

        mock_moxie_source.assert_called_once()
        kwargs = mock_moxie_source.call_args.kwargs
        assert kwargs["base_url"] == self.config.base_url
        assert kwargs["api_key"] == self.config.api_key
        assert kwargs["endpoint"] == "projects"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
