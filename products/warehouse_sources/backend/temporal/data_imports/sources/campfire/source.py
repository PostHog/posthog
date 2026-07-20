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
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.campfire import (
    CampfireResumeConfig,
    campfire_source,
    validate_credentials as validate_campfire_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import (
    CAMPFIRE_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CampfireSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CampfireSource(ResumableSource[CampfireSourceConfig, CampfireResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.campfire.ai/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAMPFIRE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAMPFIRE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Campfire",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["erp", "meetcampfire"],
            caption="""Enter your Campfire API key to pull your accounting data into the PostHog Data warehouse.

Create an API user and key on the [API keys page](https://app.meetcampfire.com/v2/settings/api-keys) in your Campfire settings. A `view only` role is enough, since PostHog only reads data. The key is shown once, so copy it when you create it.
""",
            iconPath="/static/services/campfire.png",
            docsUrl="https://posthog.com/docs/cdp/sources/campfire",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.meetcampfire.com": "Your Campfire API key is invalid or has been revoked. Create a new API key in your Campfire settings (Settings > API keys), then reconnect.",
            "403 Client Error: Forbidden for url: https://api.meetcampfire.com": "Your Campfire API key does not have permission to read this data. Check the API user's role in your Campfire settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: CampfireSourceConfig,
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
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CampfireSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        endpoint_config = CAMPFIRE_ENDPOINTS.get(schema_name) if schema_name else None
        if validate_campfire_credentials(config.api_key, path=endpoint_config.path if endpoint_config else None):
            return True, None

        return False, "Invalid Campfire API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CampfireResumeConfig]:
        return ResumableSourceManager[CampfireResumeConfig](inputs, CampfireResumeConfig)

    def source_for_pipeline(
        self,
        config: CampfireSourceConfig,
        resumable_source_manager: ResumableSourceManager[CampfireResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return campfire_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
