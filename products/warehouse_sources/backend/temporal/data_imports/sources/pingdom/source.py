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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PingdomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom import (
    PingdomResumeConfig,
    pingdom_source,
    validate_credentials as validate_pingdom_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PingdomSource(ResumableSource[PingdomSourceConfig, PingdomResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINGDOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.pingdom.com": "Pingdom authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://api.pingdom.com": "Pingdom denied access. Please check that your API token has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PINGDOM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Pingdom",
            caption="""Enter your Pingdom API token to pull your Pingdom uptime monitoring data into the PostHog Data warehouse.

You can create an API token in [My Pingdom](https://my.pingdom.com/app/api-tokens) under Settings > Pingdom API. A read-only token is sufficient.""",
            iconPath="/static/services/pingdom.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pingdom",
            releaseStatus=ReleaseStatus.ALPHA,
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PingdomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: PingdomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_pingdom_credentials(config.api_token):
            return True, None

        return False, "Invalid Pingdom API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PingdomResumeConfig]:
        return ResumableSourceManager[PingdomResumeConfig](inputs, PingdomResumeConfig)

    def source_for_pipeline(
        self,
        config: PingdomSourceConfig,
        resumable_source_manager: ResumableSourceManager[PingdomResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pingdom_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
