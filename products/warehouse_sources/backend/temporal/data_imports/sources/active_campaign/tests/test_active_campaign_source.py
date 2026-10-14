from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.source import ActiveCampaignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.activecampaign import (
    ActiveCampaignSourceConfig,
)


class TestActiveCampaignSource:
    def setup_method(self) -> None:
        self.source = ActiveCampaignSource()
        self.team_id = 123
        self.config = ActiveCampaignSourceConfig(api_url="https://acme.api-us1.com", api_key="test-key")

    def test_api_url_is_a_connection_host_field(self) -> None:
        # Changing api_url must force the api_key to be re-entered, so the stored
        # key is never sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["api_url"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts"])
        assert len(schemas) == 1
        assert schemas[0].name == "contacts"
