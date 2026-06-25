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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GongSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong import (
    GONG_BASE_URL,
    GongResumeConfig,
    gong_source,
    validate_credentials as validate_gong_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.settings import GONG_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GongSource(ResumableSource[GongSourceConfig, GongResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GONG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GONG,
            category=DataWarehouseSourceCategory.SALES,
            label="Gong",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Gong API credentials to pull your Gong data into the PostHog Data warehouse.

Create an **Access Key** and **Access Key Secret** in Gong under **Company Settings > Ecosystem > API**.

Grant the following read scopes so the connected endpoints can sync:
- `api:calls:read:basic`
- `api:users:read`
- `api:settings:scorecards:read`
- `api:workspaces:read`
""",
            iconPath="/static/services/gong.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gong",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Gong access key",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_key_secret",
                        label="Access key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Gong access key secret",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gong.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GongSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                description="Only syncs the last 365 days on initial sync"
                if endpoint_config.uses_date_window
                else None,
            )
            for endpoint, endpoint_config in GONG_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GongSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gong_credentials(config.access_key, config.access_key_secret, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {GONG_BASE_URL}": "Your Gong access key or secret is invalid. Please generate new credentials and reconnect.",
            f"403 Client Error: Forbidden for url: {GONG_BASE_URL}": "Your Gong credentials do not have the required permissions. Please check the granted scopes and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GongResumeConfig]:
        return ResumableSourceManager[GongResumeConfig](inputs, GongResumeConfig)

    def source_for_pipeline(
        self,
        config: GongSourceConfig,
        resumable_source_manager: ResumableSourceManager[GongResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gong_source(
            access_key=config.access_key,
            access_key_secret=config.access_key_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
