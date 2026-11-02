from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightdash import (
    LightdashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.source import LightdashSource


class TestLightdashSource:
    def setup_method(self) -> None:
        self.source = LightdashSource()
        self.team_id = 123
        self.config = LightdashSourceConfig(instance_url="https://app.lightdash.cloud", api_token="tok")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping this would let an editor retarget the stored token at a host they control
        # without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["instance_url"]
