from products.warehouse_sources.backend.facade.source_config import (
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zapiersupportedstorage import (
    ZapierSupportedStorageSourceConfig,
)
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

    def test_get_schemas_filtered_by_names(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["records"])[0].name == "records"
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
