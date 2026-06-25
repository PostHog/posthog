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
from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted import (
    DelightedResumeConfig,
    delighted_source,
    validate_credentials as validate_delighted_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DelightedSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DelightedSource(ResumableSource[DelightedSourceConfig, DelightedResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DELIGHTED

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.delighted.com": "Delighted authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url: https://api.delighted.com": "Delighted denied access. Please check that your API key has access to this project.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DELIGHTED,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Delighted",
            caption="""Enter your Delighted API key to pull your survey data into the PostHog Data warehouse.

You can find your API key in your Delighted account under **Settings → API**. Each Delighted project has its own API key with read access to that project's data.""",
            iconPath="/static/services/delighted.png",
            docsUrl="https://posthog.com/docs/cdp/sources/delighted",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DelightedSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(incremental_fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=incremental_fields is not None,
                incremental_fields=incremental_fields or [],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: DelightedSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_delighted_credentials(config.api_key):
            return True, None

        return False, "Invalid Delighted API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DelightedResumeConfig]:
        return ResumableSourceManager[DelightedResumeConfig](inputs, DelightedResumeConfig)

    def source_for_pipeline(
        self,
        config: DelightedSourceConfig,
        resumable_source_manager: ResumableSourceManager[DelightedResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return delighted_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
