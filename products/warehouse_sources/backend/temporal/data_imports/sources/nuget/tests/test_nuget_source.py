import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NugetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.nuget import NugetResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.settings import ENDPOINTS, NUGET_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source import NugetSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestNugetSource:
    def setup_method(self):
        self.source = NugetSource()
        self.team_id = 123
        self.config = NugetSourceConfig(package_ids="Newtonsoft.Json, Serilog")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.NUGET

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Nuget"
        assert config.label == "NuGet"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/nuget.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/nuget"

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["package_ids"]
        assert fields[0].type == SourceFieldInputConfigType.TEXTAREA
        assert fields[0].required is True
        assert fields[0].secret is False

    def test_get_schemas_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the catalog exposes a server-side time cursor; search/registrations are id-keyed.
        assert schemas["catalog_events"].supports_incremental is True
        assert schemas["catalog_events"].supports_append is True
        assert [f["field"] for f in schemas["catalog_events"].incremental_fields] == ["commit_timestamp"]
        assert schemas["catalog_events"].should_sync_default is False
        for name in ("packages", "package_versions"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []
            assert schemas[name].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["packages"])
        assert [schema.name for schema in schemas] == ["packages"]

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        assert set(self.source.get_canonical_descriptions()) == set(NUGET_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "These package IDs were not found on NuGet: Nope.One"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source.validate_nuget_connection"
    )
    def test_validate_credentials_plumbs_result(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_validate.assert_called_once_with("Newtonsoft.Json, Serilog")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source.validate_nuget_connection"
    )
    def test_validate_credentials_surfaces_empty_package_list(self, mock_validate):
        mock_validate.side_effect = ValueError("Enter at least one NuGet package ID (comma-separated).")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "at least one NuGet package ID" in (error_message or "")

    def test_non_retryable_errors_match_package_not_found(self):
        observed = "NuGet package not found: no NuGet package with id 'Nope.One' exists"
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "transient_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.nuget.org/v3/catalog0/index.json",
            "500 Server Error: Internal Server Error for url: https://azuresearch-usnc.nuget.org/query",
            "HTTPSConnectionPool(host='api.nuget.org', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, transient_error):
        assert not any(key in transient_error for key in self.source.get_non_retryable_errors())

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is NugetResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source.nuget_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_nuget_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "catalog_events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_nuget_source.call_args.kwargs
        assert kwargs["package_ids"] == "Newtonsoft.Json, Serilog"
        assert kwargs["endpoint"] == "catalog_events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source.nuget_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_nuget_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "packages"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_nuget_source.call_args.kwargs["db_incremental_field_last_value"] is None
