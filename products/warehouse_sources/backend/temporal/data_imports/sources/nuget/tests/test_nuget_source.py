import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuget import NugetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source import NugetSource


class TestNugetSource:
    def setup_method(self):
        self.source = NugetSource()
        self.team_id = 123
        self.config = NugetSourceConfig(package_ids="Newtonsoft.Json, Serilog")

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
