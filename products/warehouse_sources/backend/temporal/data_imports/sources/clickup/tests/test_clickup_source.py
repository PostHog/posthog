from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source import ClickUpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clickup import (
    ClickUpSourceConfig,
)


class TestClickUpSource:
    def setup_method(self) -> None:
        self.source = ClickUpSource()
        self.team_id = 123
        self.config = ClickUpSourceConfig(api_key="pk_token", workspace_id="9008123456")

    def test_workspace_id_is_a_connection_host_field(self) -> None:
        # Changing the workspace the token targets must re-require the token.
        assert self.source.connection_host_fields == ["workspace_id"]
