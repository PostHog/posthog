from typing import Optional, cast

import structlog

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cosmosdb.cosmosdb import (
    FORBIDDEN_MESSAGE,
    CosmosDBClient,
    CosmosDBResumeConfig,
    CosmosDBTsCursor,
    cosmosdb_source,
    hostname_of,
    validate_credentials as validate_cosmosdb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cosmosdb.settings import (
    API_VERSION,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cosmosdb import (
    CosmosDBSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CosmosDBSource(
    ResumableSource[CosmosDBSourceConfig, CosmosDBResumeConfig],
    CursorSource[CosmosDBTsCursor],
    ValidateDatabaseHostMixin,
):
    codebase_detection = detect(
        env=("^(AZURE_COSMOS|COSMOS_DB|COSMOSDB)_",),
        npm=("@azure/cosmos",),
        pypi=("azure-cosmos",),
        go=("github.com/Azure/azure-sdk-for-go/sdk/data/azcosmos",),
        maven=("com.azure:azure-cosmos",),
    )

    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://learn.microsoft.com/en-us/rest/api/cosmos-db/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COSMOSDB

    @property
    def credential_kind(self) -> str | None:
        return "cosmosdb"

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored key signs every request to this endpoint, so retargeting it must re-require the key.
        return ["account_endpoint"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COSMOSDB,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["azure cosmos", "documentdb"],
            label="Azure Cosmos DB",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Sync the containers of an Azure Cosmos DB for NoSQL database into the PostHog Data warehouse. Each container becomes a table, and incremental syncs use the `_ts` system property Cosmos stamps on every write.

Enter the account endpoint (`https://<account>.documents.azure.com`), a read-only or read-write key from the account's **Keys** page, and the database to sync. Only the NoSQL API is supported.""",
            iconPath="/static/services/cosmosdb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cosmosdb",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_endpoint",
                        label="Account endpoint",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://<account>.documents.azure.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key",
                        label="Account key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url:": "Azure Cosmos DB rejected the account key. Copy a current key from the account's Keys page and reconnect.",
            "403 Client Error: Forbidden for url:": FORBIDDEN_MESSAGE,
            "404 Client Error:": "The database or container no longer exists in this Cosmos DB account. Check the source settings and the table list.",
            "Azure Cosmos DB account key is not valid base64": "The account key is not valid. Copy the primary or secondary key from the account's Keys page and reconnect.",
        }

    def get_retryable_errors(self) -> set[str]:
        return {"Azure Cosmos DB error (retryable)"}

    def _check_host(self, config: CosmosDBSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            host = hostname_of(config.account_endpoint)
        except ValueError as error:
            return False, str(error)
        return self.is_database_host_valid(host, team_id)

    def get_schemas(
        self,
        config: CosmosDBSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        host_valid, host_error = self._check_host(config, team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Azure Cosmos DB account endpoint")

        client = CosmosDBClient(
            config.account_endpoint, config.key, self.resolve_api_version(api_version), structlog.get_logger(__name__)
        )
        schemas = [
            SourceSchema(
                name=collection.id,
                supports_incremental=True,
                # The `>=` watermark re-reads its boundary second, which only merge dedupes.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS,
            )
            for collection in client.list_collections(config.database)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: CosmosDBSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host_valid, host_error = self._check_host(config, team_id)
        if not host_valid:
            return False, host_error

        return validate_cosmosdb_credentials(
            endpoint=config.account_endpoint,
            key=config.key,
            database=config.database,
            api_version=self.resolve_api_version(api_version),
        )

    def cursor_class(self) -> type[CosmosDBTsCursor]:
        return CosmosDBTsCursor

    def merge_cursors(self, current: CosmosDBTsCursor, candidate: CosmosDBTsCursor) -> CosmosDBTsCursor:
        return candidate if candidate.ts_floor >= current.ts_floor else current

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CosmosDBResumeConfig]:
        return ResumableSourceManager[CosmosDBResumeConfig](inputs, CosmosDBResumeConfig)

    def source_for_pipeline(
        self,
        config: CosmosDBSourceConfig,
        resumable_source_manager: ResumableSourceManager[CosmosDBResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self._check_host(config, inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Azure Cosmos DB account endpoint")

        return cosmosdb_source(
            endpoint=config.account_endpoint,
            key=config.key,
            database=config.database,
            collection_name=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            # The pipeline always builds one for a cursor source; the test drivers do not.
            cursor_manager=inputs.source_cursor,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
