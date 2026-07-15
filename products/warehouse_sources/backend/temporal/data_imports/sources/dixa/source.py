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
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa import (
    DixaResumeConfig,
    dixa_source,
    validate_credentials as validate_dixa_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DixaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DixaSource(ResumableSource[DixaSourceConfig, DixaResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.dixa.io"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DIXA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://dev.dixa.io": "Dixa authentication failed. Please check your API token.",
            "401 Client Error: Unauthorized for url: https://exports.dixa.io": "Dixa authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://dev.dixa.io": "Dixa denied access. Please check that your API token has the required permissions.",
            "403 Client Error: Forbidden for url: https://exports.dixa.io": "Dixa denied access. Please check that your API token has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DIXA,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Dixa",
            caption="""Enter your Dixa API token to pull your Dixa customer service data into the PostHog Data warehouse.

An admin can generate an API token in Dixa under Settings > Integrations > API Tokens. The same token covers both the main API (agents, queues, tags, end users) and the Exports API (conversations). Note that conversation exports are rate limited to 10 requests per minute, so large historical backfills take a while.""",
            iconPath="/static/services/dixa.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dixa",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DixaSourceConfig,
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
        self, config: DixaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_dixa_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DixaResumeConfig]:
        return ResumableSourceManager[DixaResumeConfig](inputs, DixaResumeConfig)

    def source_for_pipeline(
        self,
        config: DixaSourceConfig,
        resumable_source_manager: ResumableSourceManager[DixaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dixa_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
