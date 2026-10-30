from typing import Any, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    DiscoveryOptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.fields import (
    FEATURE_FLAG,
    KEYWORDS,
    discovery_options_from,
    file_option_fields,
    secret_field,
    source_caption,
    url_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    AZURE_EXAMPLE_URL,
    parse_azure_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
    UnmappableTableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureblob import (
    AzureBlobSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureBlobSource(ObjectStorageSource[AzureBlobSourceConfig]):
    codebase_detection = detect(
        env=("^AZURE_STORAGE_",),
        npm=("@azure/storage-blob",),
        pypi=("azure-storage-blob", "adlfs"),
        go=("github.com/Azure/azure-sdk-for-go/sdk/storage/azblob",),
        maven=("com.azure:azure-storage-blob",),
    )

    api_docs_url = "https://learn.microsoft.com/en-us/rest/api/storageservices/blob-service-rest-api"
    requires_team_feature_flag = FEATURE_FLAG
    self_managed_service = "azure"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREBLOB

    @property
    def connection_host_fields(self) -> list[str]:
        # The URL picks the account and container the stored key is sent to, so changing it must re-require the key.
        return ["url_pattern"]

    def object_store_config(self, config: AzureBlobSourceConfig) -> AzureBlobConfig:
        return AzureBlobConfig.from_url(parse_azure_url(config.url_pattern), account_key=config.account_key.strip())

    def discovery_options(self, config: AzureBlobSourceConfig) -> DiscoveryOptions:
        return discovery_options_from(config)

    def self_managed_connection_inputs(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        # ClickHouse reads Azure with the storage account name as the access key. A key for another
        # account than the URL's never read these files, so it isn't moved to this one.
        if credential.access_key.strip().lower() != location.account:
            raise UnmappableTableError("the access key isn't the storage account name in the URL")
        return {
            "url_pattern": f"https://{location.account}.blob.core.windows.net/{location.bucket}/",
            "account_key": credential.access_secret,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREBLOB,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["azure", "blob storage", "adls", *KEYWORDS],
            label="Azure Blob Storage",
            caption=source_caption("an Azure Blob Storage container"),
            iconPath="/static/services/azure_blob.png",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=cast(
                list[FieldType],
                [
                    url_field(AZURE_EXAMPLE_URL),
                    secret_field(
                        "account_key",
                        "Account key",
                        caption="Find it in the Azure portal, on the storage account's Access keys page.",
                    ),
                    *file_option_fields(),
                ],
            ),
        )
