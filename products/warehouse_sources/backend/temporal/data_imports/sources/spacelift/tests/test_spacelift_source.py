from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spacelift import (
    SpaceliftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source import SpaceliftSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source"


class TestSpaceliftSource:
    def setup_method(self):
        self.source = SpaceliftSource()
        self.team_id = 123
        self.config = SpaceliftSourceConfig(account_name="my-company", api_key_id="key-id", api_key_secret="key-secret")

    def test_account_name_is_a_connection_host_field(self):
        # Retargeting the account subdomain must force re-entering the API secret,
        # otherwise a PATCH could redirect the stored secret to an attacker's host.
        assert self.source.connection_host_fields == ["account_name"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["runs", "stacks"])
        assert {schema.name for schema in schemas} == {"runs", "stacks"}
