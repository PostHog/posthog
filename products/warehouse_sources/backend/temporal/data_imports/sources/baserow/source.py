from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow import (
    BaserowResumeConfig,
    baserow_rows_source,
    build_schema_name_map,
    check_table_read_permission,
    hostname_of,
    list_tables,
    normalize_base_url,
    resolve_table_id,
    validate_credentials as validate_baserow_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.baserow import (
    BaserowSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BaserowSource(ResumableSource[BaserowSourceConfig, BaserowResumeConfig], ValidateDatabaseHostMixin):
    # Baserow's REST API carries no version segment or version header.
    api_docs_url = "https://baserow.io/api-docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BASEROW

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` decides where the stored database token is sent; retargeting it must
        # re-require the token so an editor can't exfiltrate it to a host they control.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BASEROW,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Baserow",
            caption="""Sync the tables from your Baserow databases into the PostHog Data warehouse — each Baserow table becomes its own warehouse table.

Create a database token in Baserow under **Settings > Database tokens** and make sure **read** permission is enabled for the tables you want to sync. Leave the instance URL blank to use Baserow's hosted service; self-hosted instances must be reachable over https.""",
            iconPath="/static/services/baserow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/baserow",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["airtable alternative", "no-code database"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="database_token",
                        label="Database token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Instance URL (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.baserow.io",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Baserow database token does not have permission for this table. Enable read access for it in Baserow's token settings.",
            "403 Client Error": "Your Baserow database token is invalid or has been revoked. Please create a new token and reconnect.",
            "404 Client Error": "The Baserow table was not found — it may have been deleted.",
            "Invalid Baserow instance URL": "The Baserow instance URL is invalid. Please enter the instance's canonical https URL.",
        }

    def get_schemas(
        self,
        config: BaserowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # One schema per Baserow table the token can see. Rows expose no server-side
        # updated-since filter, so every table is full refresh only.
        tables_by_name = build_schema_name_map(list_tables(config.base_url, config.database_token))
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                schema_metadata={"table_id": table["id"], "database_id": table["database_id"]},
            )
            for name, table in sorted(tables_by_name.items())
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_endpoint_permissions(
        self, config: BaserowSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        # Database tokens have per-table read toggles, so surface unreadable tables in the
        # schema picker instead of failing the sync later.
        result: dict[str, str | None] = dict.fromkeys(endpoints)
        try:
            tables_by_name = build_schema_name_map(list_tables(config.base_url, config.database_token))
        except Exception:
            return result
        for name in endpoints:
            table = tables_by_name.get(name)
            if table is None:
                continue
            result[name] = check_table_read_permission(config.base_url, config.database_token, int(table["id"]))
        return result

    def validate_credentials(
        self,
        config: BaserowSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            base = normalize_base_url(config.base_url)
        except ValueError:
            return False, "Invalid Baserow instance URL"

        host_valid, host_error = self.is_database_host_valid(hostname_of(base), team_id)
        if not host_valid:
            return False, host_error

        ok, status = validate_baserow_credentials(config.base_url, config.database_token)
        if ok:
            return True, None
        # Unlike most APIs, Baserow returns 403 for a token that doesn't exist
        # (ERROR_TOKEN_DOES_NOT_EXIST), so 403 at create still means a bad token.
        if status in (401, 403):
            return False, "Invalid Baserow database token"
        return False, "Could not connect to Baserow. Please check the instance URL."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BaserowResumeConfig]:
        return ResumableSourceManager[BaserowResumeConfig](inputs, BaserowResumeConfig)

    def source_for_pipeline(
        self,
        config: BaserowSourceConfig,
        resumable_source_manager: ResumableSourceManager[BaserowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.base_url), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Baserow host")

        table_id = resolve_table_id(config.base_url, config.database_token, inputs.schema_name, inputs.schema_metadata)
        return baserow_rows_source(
            base_url=config.base_url,
            database_token=config.database_token,
            table_id=table_id,
            schema_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
