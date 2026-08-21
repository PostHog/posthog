from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
    AZURE_DEVOPS_VERSION_7_2,
    AZURE_DEVOPS_VERSION_LEGACY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source import AzureDevOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azuredevops import (
    AzureDevOpsSourceConfig,
)


class TestAzureDevOpsSource:
    def setup_method(self):
        self.source = AzureDevOpsSource()
        self.team_id = 123
        self.config = AzureDevOpsSourceConfig(organization="myorg", personal_access_token="pat")

    def test_default_version_is_the_new_ga_version(self):
        # New sources start on 7.2; the legacy label stays supported so existing pins keep working.
        assert self.source.default_version == AZURE_DEVOPS_VERSION_7_2
        assert set(self.source.supported_versions) == {AZURE_DEVOPS_VERSION_LEGACY, AZURE_DEVOPS_VERSION_7_2}
