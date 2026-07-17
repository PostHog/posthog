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
from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory import (
    ENDPOINTS,
    FullStoryResumeConfig,
    fullstory_source,
    validate_credentials as validate_fullstory_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FullStorySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FullStorySource(ResumableSource[FullStorySourceConfig, FullStoryResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.fullstory.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FULLSTORY

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.fullstory.com": "Fullstory authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url: https://api.fullstory.com": "Fullstory denied access. Please check that your API key has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FULL_STORY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Fullstory",
            caption="""Enter your Fullstory API key to pull your Fullstory user data into the PostHog Data warehouse.

You can create an API key in Fullstory under Settings > Integrations & API Keys > API Keys. A key with at least the Viewer permission level is sufficient for syncing.""",
            iconPath="/static/services/fullstory.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fullstory",
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

    def get_schemas(
        self,
        config: FullStorySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The users listing has no updated-since filter; session/event data
        # only exists behind async Data Export jobs (a follow-up).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: FullStorySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_fullstory_credentials(config.api_key):
            return True, None

        return False, "Invalid Fullstory API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FullStoryResumeConfig]:
        return ResumableSourceManager[FullStoryResumeConfig](inputs, FullStoryResumeConfig)

    def source_for_pipeline(
        self,
        config: FullStorySourceConfig,
        resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fullstory_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
