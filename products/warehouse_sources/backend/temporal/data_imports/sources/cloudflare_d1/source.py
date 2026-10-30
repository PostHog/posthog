from typing import Optional, cast

from requests import RequestException

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_d1.cloudflare_d1 import (
    INVALID_TOKEN_MESSAGE,
    NOT_FOUND_MESSAGE,
    PERMISSION_MESSAGE,
    UNREACHABLE_MESSAGE,
    D1Client,
    D1QueryError,
    D1ResumeConfig,
    integer_primary_key,
    iter_table_rows,
    pages_by_keyset,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_d1.settings import (
    incremental_type_for_declared_type,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    build_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflared1 import (
    CloudflareD1SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField


@SourceRegistry.register
class CloudflareD1Source(ResumableSource[CloudflareD1SourceConfig, D1ResumeConfig]):
    # A D1 binding lives in wrangler.toml, which carries no package, env key or script tag.
    codebase_detection = NOT_DETECTABLE
    detects_primary_keys = True

    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://developers.cloudflare.com/api/resources/d1/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARED1

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOUDFLARED1,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Cloudflare D1",
            keywords=["sqlite", "cloudflare", "workers", "d1"],
            caption="""Sync the tables of a Cloudflare D1 database into the PostHog Data warehouse.

Create an API token in the [Cloudflare dashboard](https://dash.cloudflare.com/profile/api-tokens) with the **D1 Read** permission for the account. The account ID and database ID are on the database's page under **Storage & Databases > D1**.""",
            iconPath="/static/services/cloudflare.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudflare-d1",
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database_id",
                        label="Database ID",
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
            "401 Client Error: Unauthorized for url: https://api.cloudflare.com": INVALID_TOKEN_MESSAGE,
            "403 Client Error: Forbidden for url: https://api.cloudflare.com": PERMISSION_MESSAGE,
            "404 Client Error: Not Found for url: https://api.cloudflare.com": NOT_FOUND_MESSAGE,
            "no such table": "The table no longer exists in the D1 database. Remove it from the source or recreate it.",
            "no such column": "The incremental column no longer exists in the D1 table. Pick another column in the table's settings.",
        }

    def validate_credentials(
        self,
        config: CloudflareD1SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            client = D1Client(config.api_token, config.account_id, config.database_id)
        except ValueError as error:
            return False, str(error)
        try:
            response = client.get_database()
        except RequestException:
            # The probe runs while a person creates the source, so an unreachable API has to be a
            # message they can act on, not an error the API answers with a generic failure.
            return False, UNREACHABLE_MESSAGE
        if response.status_code == 200:
            return True, None
        if response.status_code == 401:
            return False, INVALID_TOKEN_MESSAGE
        if response.status_code == 403:
            return False, PERMISSION_MESSAGE
        if response.status_code == 404:
            return False, NOT_FOUND_MESSAGE
        return False, UNREACHABLE_MESSAGE

    def get_schemas(
        self,
        config: CloudflareD1SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        client = D1Client(config.api_token, config.account_id, config.database_id)
        schemas: list[SourceSchema] = []
        tables = client.list_tables(names)
        keyset_tables = [table for table in tables if pages_by_keyset(table)]
        indexed = client.leading_index_columns([table.name for table in keyset_tables])
        for table in tables:
            triples = [
                (name, field_type, nullable)
                for name, declared_type, nullable in table.columns
                if (field_type := incremental_type_for_declared_type(declared_type)) is not None
            ]
            incremental_fields: list[IncrementalField] = []
            if table in keyset_tables:
                # Every page orders by the cursor, and D1 bills each row a query reads, so the UI
                # warns when the column leads no index.
                indexed_columns = indexed.get(table.name, set())
                if (rowid_key := integer_primary_key(table)) is not None:
                    indexed_columns = indexed_columns | {rowid_key}
                incremental_fields = build_incremental_fields(triples, indexed_columns)
            schemas.append(
                SourceSchema(
                    name=table.name,
                    supports_incremental=bool(incremental_fields),
                    # The watermark comparison is inclusive, so only a merge keeps re-read rows single.
                    supports_append=False,
                    incremental_fields=incremental_fields,
                    columns=list(table.columns),
                    detected_primary_keys=list(table.primary_keys) or None,
                    row_count=self._count_rows(client, table.name) if with_counts else None,
                )
            )
        return schemas

    @staticmethod
    def _count_rows(client: D1Client, table: str) -> int | None:
        # Only a progress estimate: a view too slow to count must not stop the sync.
        try:
            return client.count_rows(table)
        except (D1QueryError, RequestException):
            return None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[D1ResumeConfig]:
        return ResumableSourceManager[D1ResumeConfig](inputs, D1ResumeConfig)

    def source_for_pipeline(
        self,
        config: CloudflareD1SourceConfig,
        resumable_source_manager: ResumableSourceManager[D1ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        client = D1Client(config.api_token, config.account_id, config.database_id)
        tables = client.list_tables([inputs.schema_name])
        if not tables:
            raise D1QueryError(f"no such table: {inputs.schema_name}")
        table = tables[0]
        incremental_field = inputs.incremental_field if inputs.should_use_incremental_field else None
        watermark = inputs.db_incremental_field_last_value if incremental_field else None
        return SourceResponse(
            name=table.name,
            items=lambda: iter_table_rows(
                client, table, incremental_field, inputs.incremental_field_type, watermark, resumable_source_manager
            ),
            primary_keys=list(table.primary_keys) or None,
            # Counting a view runs its whole query once more, so only tables get an estimate.
            rows_to_sync=self._count_rows(client, table.name)
            if incremental_field is None and table.has_rowid
            else None,
            sort_mode="asc",
        )
