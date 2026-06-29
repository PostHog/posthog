from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrttoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.ortto import (
    OrttoResumeConfig,
    ortto_source,
    validate_credentials as validate_ortto_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OrttoSource(ResumableSource[OrttoSourceConfig, OrttoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORTTO

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Ortto authentication failed. Please check your API key (and that it matches the selected region).",
            "403 Client Error: Forbidden for url": "Ortto denied access. Please check your API key's permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ORTTO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Ortto",
            caption="""Connect your Ortto account to pull your marketing data into the PostHog Data warehouse.

Create a custom API key in Ortto under Settings > API keys, and pick the region your Ortto instance lives in. Ortto's API has no updated-since filter, so all tables fully refresh on each sync.""",
            iconPath="/static/services/ortto.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ortto",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="global",
                        options=[
                            SourceFieldSelectConfigOption(label="Global", value="global"),
                            SourceFieldSelectConfigOption(label="Australia", value="au"),
                            SourceFieldSelectConfigOption(label="Europe", value="eu"),
                        ],
                    ),
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
        config: OrttoSourceConfig,
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
        self, config: OrttoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_ortto_credentials(config.region, config.api_key):
            return True, None

        return False, "Invalid Ortto credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OrttoResumeConfig]:
        return ResumableSourceManager[OrttoResumeConfig](inputs, OrttoResumeConfig)

    def source_for_pipeline(
        self,
        config: OrttoSourceConfig,
        resumable_source_manager: ResumableSourceManager[OrttoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ortto_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
