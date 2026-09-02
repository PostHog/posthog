from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zapiersupportedstorage import (
    ZapierSupportedStorageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.source import (
    ZapierSupportedStorageSource,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.source"


class TestZapierSupportedStorageSource:
    def setup_method(self) -> None:
        self.source = ZapierSupportedStorageSource()
        self.team_id = 123
        self.config = ZapierSupportedStorageSourceConfig(secret="abcdef01-2345-4678-9abc-def012345678")

    def test_get_source_config_single_secret_field(self) -> None:
        config = self.source.get_source_config

        assert config.releaseStatus == ReleaseStatus.ALPHA
        # docsUrl must match the doc filename so the posthog.com page resolves.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zapier-supported-storage"

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["secret"]
        secret = fields[0]
        # The store secret is the sole credential and must be handled as a password/secret.
        assert secret.type == SourceFieldInputConfigType.PASSWORD
        assert secret.secret is True
        assert secret.required is True

    def test_get_schemas_single_full_refresh_table(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS) == {"records"}
        # The store has no timestamps, so nothing supports incremental or append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["records"])[0].name == "records"
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        # A static endpoint catalog opts into public docs; get_documented_tables must succeed with
        # no credentials and surface the records table as full refresh.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert [t["name"] for t in tables] == ["records"]
        assert "Full refresh" in tables[0]["sync_methods"]
