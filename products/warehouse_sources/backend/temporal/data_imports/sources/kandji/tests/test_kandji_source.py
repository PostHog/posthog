from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kandji import KandjiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.source import KandjiSource


class TestKandjiSource:
    def setup_method(self) -> None:
        self.source = KandjiSource()
        self.team_id = 123
        self.config = KandjiSourceConfig(api_token="tok", subdomain="accuhive", region="us")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert [s.name for s in schemas] == ["devices"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping either field would let an editor retarget the stored bearer token at a host
        # they control without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["subdomain", "region"]
