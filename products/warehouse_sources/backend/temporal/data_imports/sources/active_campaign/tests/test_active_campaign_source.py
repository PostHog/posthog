import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.settings import ENDPOINTS
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

    @pytest.mark.parametrize(
        "raised_message",
        [
            # `active_campaign_source` raises `ActiveCampaign API URL is not allowed: {reason}` for
            # every URL-validation failure; the sync matcher is a substring check, so the stable
            # prefix must classify each reason as non-retryable regardless of the appended detail.
            "ActiveCampaign API URL is not allowed: Could not resolve host",
            "ActiveCampaign API URL is not allowed: Private IP address not allowed",
        ],
    )
    def test_url_not_allowed_is_non_retryable(self, raised_message: str) -> None:
        keys = self.source.get_non_retryable_errors().keys()
        assert any(key in raised_message for key in keys)

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint advertises a curl-verified server-side filter yet, so every
        # schema is full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts"])
        assert len(schemas) == 1
        assert schemas[0].name == "contacts"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []
