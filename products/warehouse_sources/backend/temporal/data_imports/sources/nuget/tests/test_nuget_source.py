import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuget import NugetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.source import NugetSource


class TestNugetSource:
    def setup_method(self):
        self.source = NugetSource()
        self.team_id = 123
        self.config = NugetSourceConfig(package_ids="Newtonsoft.Json, Serilog")

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
