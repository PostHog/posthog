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
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper import (
    CopperResumeConfig,
    copper_source,
    validate_credentials as validate_copper_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CopperSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CopperSource(ResumableSource[CopperSourceConfig, CopperResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COPPER

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.copper.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Copper authentication failed. Check your API key and the email it belongs to.",
            "403 Client Error": "Copper access forbidden. Check that your API key has access to this data.",
        }

    def get_schemas(
        self,
        config: CopperSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CopperSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_copper_credentials(config.api_key, config.user_email)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CopperResumeConfig]:
        return ResumableSourceManager[CopperResumeConfig](inputs, CopperResumeConfig)

    def source_for_pipeline(
        self,
        config: CopperSourceConfig,
        resumable_source_manager: ResumableSourceManager[CopperResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return copper_source(
            api_key=config.api_key,
            user_email=config.user_email,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COPPER,
            category=DataWarehouseSourceCategory.CRM,
            label="Copper",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Copper CRM data into the PostHog Data warehouse.

Generate an API key in Copper under **Settings → Integrations → API Keys**. The email below must be the email of the user the API key belongs to.""",
            iconPath="/static/services/copper.png",
            docsUrl="https://posthog.com/docs/cdp/sources/copper",
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
                        name="user_email",
                        label="User email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                ],
            ),
        )
