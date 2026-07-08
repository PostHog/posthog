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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion import (
    NotionResumeConfig,
    notion_source,
    validate_credentials as validate_notion_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NotionSource(ResumableSource[NotionSourceConfig, NotionResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOTION

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.notion.com": "Your Notion integration token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.notion.com": "Your Notion integration is missing the required capabilities, or the pages/databases you want to sync have not been shared with it.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NOTION,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Notion",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Notion internal integration token to pull your Notion data into the PostHog Data warehouse.

Create an internal integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy its token (starts with `ntn_` or `secret_`).

Then **share** each page or database you want to sync with the integration (via the page's `•••` menu → Connections), otherwise it will not be visible to the sync.
""",
            iconPath="/static/services/notion.png",
            docsUrl="https://posthog.com/docs/cdp/sources/notion",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="ntn_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.notion.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: NotionSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NotionSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_notion_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NotionResumeConfig]:
        return ResumableSourceManager[NotionResumeConfig](inputs, NotionResumeConfig)

    def source_for_pipeline(
        self,
        config: NotionSourceConfig,
        resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return notion_source(
            token=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
