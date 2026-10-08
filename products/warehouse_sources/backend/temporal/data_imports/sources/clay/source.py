from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clay.clay import (
    ClayResumeConfig,
    clay_source,
    parse_table_ids,
    validate_credentials as validate_clay_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clay import ClaySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClaySource(ResumableSource[ClaySourceConfig, ClayResumeConfig]):
    supported_versions = ("v0",)
    default_version = "v0"
    api_docs_url = "https://developers.clay.com/tables"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLAY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clay.com": (
                "Clay rejected the API key. Create a new key under Settings > Account > API keys in Clay "
                "and update the source."
            ),
            "403 Client Error: Forbidden for url: https://api.clay.com": (
                "Clay denied access to this table. Turn on Enable for API in the table's settings "
                "(Edit table settings > Integrations). This needs a Clay Enterprise plan, and the API key's "
                "user must have access to the table."
            ),
            "404 Client Error: Not Found for url: https://api.clay.com": (
                "Clay could not find this table. It may have been deleted, or the table ID may be wrong."
            ),
        }

    def get_schemas(
        self,
        config: ClaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        table_ids = parse_table_ids(config.table_ids)
        if names is not None:
            table_ids = [table_id for table_id in table_ids if table_id in names]
        return [
            SourceSchema(name=table_id, supports_incremental=False, supports_append=False) for table_id in table_ids
        ]

    def validate_credentials(
        self,
        config: ClaySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        table_ids = [schema_name] if schema_name else parse_table_ids(config.table_ids)
        return validate_clay_credentials(config.api_key, table_ids)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClayResumeConfig]:
        return ResumableSourceManager[ClayResumeConfig](inputs, ClayResumeConfig)

    def source_for_pipeline(
        self,
        config: ClaySourceConfig,
        resumable_source_manager: ResumableSourceManager[ClayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clay_source(
            api_key=config.api_key,
            table_id=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLAY,
            category=DataWarehouseSourceCategory.CRM,
            label="Clay",
            caption=(
                "Sync rows from your Clay tables. Reading tables through the Clay API needs a Clay Enterprise plan. "
                "Create an API key in Clay under **Settings > Account > API keys**, and turn on **Enable for API** "
                "in each table's settings (**Edit table settings > Integrations**). "
                "Clay's API can't list tables, so paste the ID or URL of each table you want to sync "
                "(the ID starts with `t_` and appears after `/tables/` in the table's URL)."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/clay",
            iconPath="/static/services/clay.png",
            keywords=["enrichment", "clay.com"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="table_ids",
                        label="Table IDs or URLs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="t_0te9i4tZEHwc9hihBXu\nhttps://app.clay.com/workspaces/123/tables/t_...",
                        secret=False,
                    ),
                ],
            ),
        )
