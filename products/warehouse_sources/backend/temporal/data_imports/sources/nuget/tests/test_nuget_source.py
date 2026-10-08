from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuget import NugetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source import NugetSource


class TestNugetSource:
    def setup_method(self):
        self.source = NugetSource()
        self.team_id = 123
        self.config = NugetSourceConfig(package_ids="Newtonsoft.Json, Serilog")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["packages"])
        assert [schema.name for schema in schemas] == ["packages"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source.validate_nuget_connection"
    )
    def test_validate_credentials_surfaces_empty_package_list(self, mock_validate):
        mock_validate.side_effect = ValueError("Enter at least one NuGet package ID (comma-separated).")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "at least one NuGet package ID" in (error_message or "")
