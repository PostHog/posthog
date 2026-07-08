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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PartnerizeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize import (
    PartnerizeResumeConfig,
    partnerize_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTNERIZE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PartnerizeSource(ResumableSource[PartnerizeSourceConfig, PartnerizeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PARTNERIZE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PARTNERIZE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Partnerize",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["affiliate", "performance horizon", "ascend"],
            caption="""Enter your Partnerize API credentials to pull your partnership and affiliate marketing data into the PostHog Data warehouse.

You can find your **user application key** and **user API key** under **Account settings** in the [Partnerize platform](https://console.partnerize.com). The publisher ID identifies the partner account whose campaigns, conversions, and clicks are synced.
""",
            iconPath="/static/services/partnerize.png",
            docsUrl="https://posthog.com/docs/cdp/sources/partnerize",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="application_key",
                        label="User application key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user_api_key",
                        label="User API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="publisher_id",
                        label="Publisher ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.partnerize.com": "Your Partnerize API credentials are invalid or have been revoked. Check your user application key and user API key under Account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.partnerize.com": "Your Partnerize credentials do not have access to this data. Check the account's permissions and the configured publisher ID, then reconnect.",
        }

    def get_schemas(
        self,
        config: PartnerizeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Conversions and clicks reports accept a server-side start_date/end_date window, so they
        # sync incrementally; campaigns and the reference catalogs expose no timestamp filter and
        # are full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PartnerizeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # A single probe of the configured partner account validates the key pair and the
        # publisher ID for every endpoint at once.
        return validate_credentials(config.application_key, config.user_api_key, config.publisher_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PartnerizeResumeConfig]:
        return ResumableSourceManager[PartnerizeResumeConfig](inputs, PartnerizeResumeConfig)

    def source_for_pipeline(
        self,
        config: PartnerizeSourceConfig,
        resumable_source_manager: ResumableSourceManager[PartnerizeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PARTNERIZE_ENDPOINTS:
            raise ValueError(f"Unknown Partnerize schema '{inputs.schema_name}'")

        return partnerize_source(
            application_key=config.application_key,
            user_api_key=config.user_api_key,
            publisher_id=config.publisher_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
