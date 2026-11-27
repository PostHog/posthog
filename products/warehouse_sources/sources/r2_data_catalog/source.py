from typing import Optional, cast

from requests import RequestException

from products.warehouse_sources.sources.r2_data_catalog._config import R2DataCatalogSourceConfig
from products.warehouse_sources.sources.r2_data_catalog.r2_data_catalog import (
    INCREMENTAL_COLUMN_MISSING_MESSAGE,
    INVALID_ACCOUNT_MESSAGE,
    INVALID_BUCKET_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    INVALID_URI_MESSAGE,
    INVALID_WATERMARK_MESSAGE,
    NO_CREDENTIALS_MESSAGE,
    NOT_FOUND_MESSAGE,
    PERMISSION_MESSAGE,
    STORAGE_PERMISSION_MESSAGE,
    TABLE_NOT_FOUND_MESSAGE,
    UNREACHABLE_MESSAGE,
    UNSUPPORTED_DELETES_MESSAGE,
    UNSUPPORTED_FORMAT_MESSAGE,
    CatalogClient,
    IcebergTable,
    R2DataCatalogError,
    R2DataCatalogResumeConfig,
    incremental_filter,
    incremental_type,
    iter_table_rows,
    resolve_table,
)
from products.warehouse_sources.sources.sdk import (
    NOT_DETECTABLE,
    DataWarehouseSourceCategory,
    FieldType,
    IncrementalField,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    source_key,
)

SOURCE_KEY = "R2DataCatalog"


@SourceRegistry.register
class R2DataCatalogSource(ResumableSource[R2DataCatalogSourceConfig, R2DataCatalogResumeConfig]):
    # Engines get the catalog URI and token from their own config, which names no package or env key.
    codebase_detection = NOT_DETECTABLE
    detects_primary_keys = True

    api_docs_url = "https://developers.cloudflare.com/basin-catalog/manage-catalogs/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def connection_host_fields(self) -> list[str]:
        # The catalog URI is where the stored API token goes, so changing it must re-require the token.
        return ["catalog_uri"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Cloudflare R2 Data Catalog",
            keywords=["iceberg", "cloudflare", "r2", "basin catalog", "lakehouse"],
            caption="""Sync the Apache Iceberg tables of a Cloudflare R2 Data Catalog into the PostHog Data warehouse.

Turn on the catalog for the R2 bucket, then create an R2 API token with the **Admin Read only** permission, which gives read access to the catalog and to R2 storage. Fill in the **Catalog URI** only when the catalog's page in the Cloudflare dashboard shows a different one than `https://catalog.cloudflarestorage.com/<account ID>/<bucket name>`.""",
            iconPath="/static/warehouse-sources/r2_data_catalog/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/r2-data-catalog",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="bucket_name",
                        label="Bucket name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-bucket",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="catalog_uri",
                        label="Catalog URI (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://catalog.cloudflarestorage.com/<account ID>/<bucket name>",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            message: message
            for message in (
                INVALID_TOKEN_MESSAGE,
                INVALID_ACCOUNT_MESSAGE,
                INVALID_BUCKET_MESSAGE,
                INVALID_URI_MESSAGE,
                INVALID_WATERMARK_MESSAGE,
                INCREMENTAL_COLUMN_MISSING_MESSAGE,
                PERMISSION_MESSAGE,
                NOT_FOUND_MESSAGE,
                TABLE_NOT_FOUND_MESSAGE,
                STORAGE_PERMISSION_MESSAGE,
                NO_CREDENTIALS_MESSAGE,
                UNSUPPORTED_DELETES_MESSAGE,
                UNSUPPORTED_FORMAT_MESSAGE,
            )
        }

    @staticmethod
    def _client(config: R2DataCatalogSourceConfig) -> CatalogClient:
        try:
            return CatalogClient(config.account_id, config.bucket_name, config.api_token, config.catalog_uri)
        except ValueError as error:
            # A bad field never fixes itself, so the sync must not retry it.
            raise R2DataCatalogError(str(error)) from error

    def validate_credentials(
        self,
        config: R2DataCatalogSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            client = self._client(config)
        except R2DataCatalogError as error:
            return False, str(error)
        try:
            # The config call checks the warehouse, the namespace list checks the token's catalog read access.
            client.list_namespaces()
            if schema_name is not None:
                resolve_table(client, schema_name)
        except R2DataCatalogError as error:
            return False, str(error)
        except RequestException:
            return False, UNREACHABLE_MESSAGE
        finally:
            client.close()
        return True, None

    def get_schemas(
        self,
        config: R2DataCatalogSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        client = self._client(config)
        try:
            if names is None:
                return [
                    self._schema(client.load_table(identifier), with_counts) for identifier in client.list_all_tables()
                ]
            # Named tables load directly, so a table past the discovery cap is still found.
            schemas: list[SourceSchema] = []
            for name in dict.fromkeys(names):
                try:
                    schemas.append(self._schema(resolve_table(client, name), with_counts))
                except R2DataCatalogError as error:
                    if not str(error).startswith(TABLE_NOT_FOUND_MESSAGE):
                        raise
            return schemas
        finally:
            client.close()

    @staticmethod
    def _schema(table: IcebergTable, with_counts: bool) -> SourceSchema:
        incremental_fields: list[IncrementalField] = []
        for column in table.columns:
            field_type = incremental_type(column)
            if field_type is not None:
                incremental_fields.append(
                    {
                        "label": column.name,
                        "type": field_type,
                        "field": column.name,
                        "field_type": field_type,
                        "nullable": not column.required,
                    }
                )
        name = table.identifier.display_name
        return SourceSchema(
            name=name,
            supports_incremental=bool(incremental_fields),
            # Rows at the watermark are read again, so only a merge keeps them single.
            supports_append=False,
            incremental_fields=incremental_fields,
            columns=[(column.name, column.type_name, not column.required) for column in table.columns],
            detected_primary_keys=table.primary_keys or None,
            row_count=table.total_records if with_counts else None,
            source_schema=".".join(table.identifier.namespace),
            source_table_name=table.identifier.name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[R2DataCatalogResumeConfig]:
        return ResumableSourceManager[R2DataCatalogResumeConfig](inputs, R2DataCatalogResumeConfig)

    def source_for_pipeline(
        self,
        config: R2DataCatalogSourceConfig,
        resumable_source_manager: ResumableSourceManager[R2DataCatalogResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        client = self._client(config)
        try:
            table = resolve_table(client, inputs.schema_name)
            row_filter = (
                incremental_filter(table, inputs.incremental_field, inputs.db_incremental_field_last_value)
                if inputs.should_use_incremental_field
                else None
            )
        except BaseException:
            client.close()
            raise
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: iter_table_rows(client, table, row_filter, resumable_source_manager, inputs.logger),
            primary_keys=table.primary_keys or None,
            rows_to_sync=table.total_records if row_filter is None else None,
            # Rows come in data file order, not in order of the incremental column.
            sort_mode=None,
        )
