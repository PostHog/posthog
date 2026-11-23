from typing import cast

from products.warehouse_sources.sources.azure_blob._config import AzureBlobSourceConfig
from products.warehouse_sources.sources.sdk import (
    AZURE_EXAMPLE_URL,
    KEYWORDS,
    AzureBlobConfig,
    DataWarehouseSourceCategory,
    DiscoveryOptions,
    ExternalDataSourceType,
    FieldType,
    ObjectStorageSource,
    ReleaseStatus,
    SourceConfig,
    SourceRegistry,
    detect,
    discovery_options_from,
    file_option_fields,
    parse_azure_url,
    secret_field,
    source_caption,
    url_field,
)


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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREBLOB,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["azure", "blob storage", "adls", *KEYWORDS],
            label="Azure Blob Storage",
            caption=source_caption("an Azure Blob Storage container"),
            iconPath="/static/services/azure_blob.png",
            releaseStatus=ReleaseStatus.GA,
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
