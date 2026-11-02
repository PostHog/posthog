from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.infisical import (
    InfisicalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.source import InfisicalSource


class TestInfisicalSource:
    def setup_method(self):
        self.source = InfisicalSource()
        self.team_id = 123
        self.config = InfisicalSourceConfig(
            base_url="https://app.infisical.com",
            organization_id="org-123",
            client_id="cid",
            client_secret="csecret",
        )

    def test_connection_host_fields_require_credential_reentry(self):
        # Both the host and the org selector gate the stored credential: changing either must
        # force re-entry so an editor who can't read the secret can't repoint it.
        assert self.source.connection_host_fields == ["base_url", "organization_id"]
