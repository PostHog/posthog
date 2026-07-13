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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LingoDevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.lingo_dev import (
    LingoDevResumeConfig,
    lingo_dev_source,
    validate_credentials as validate_lingo_dev_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.settings import (
    ENDPOINTS,
    LINGO_DEV_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LingoDevSource(ResumableSource[LingoDevSourceConfig, LingoDevResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINGODEV

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINGO_DEV,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Lingo.dev",
            caption="""Enter your Lingo.dev API key to automatically pull your Lingo.dev localization job data into the PostHog Data warehouse.

You can create an API key in your [Lingo.dev dashboard](https://lingo.dev/app). API keys are scoped to an organization and are only shown once at creation.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/lingo-dev",
            iconPath="/static/services/lingo_dev.png",
            keywords=["localization", "translation", "i18n", "ai"],
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
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LingoDevSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Lingo.dev has no server-side timestamp filters, so only full refresh is supported.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=LINGO_DEV_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.lingo.dev": "Your Lingo.dev API key is invalid or has been revoked. Please create a new API key in your Lingo.dev dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.lingo.dev": "Your Lingo.dev API key does not have permission to access this endpoint. Please check the key in your Lingo.dev dashboard.",
        }

    def validate_credentials(
        self, config: LingoDevSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_lingo_dev_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LingoDevResumeConfig]:
        return ResumableSourceManager[LingoDevResumeConfig](inputs, LingoDevResumeConfig)

    def source_for_pipeline(
        self,
        config: LingoDevSourceConfig,
        resumable_source_manager: ResumableSourceManager[LingoDevResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lingo_dev_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
