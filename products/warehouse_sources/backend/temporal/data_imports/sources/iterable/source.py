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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IterableSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable import (
    IterableResumeConfig,
    iterable_source,
    validate_credentials as validate_iterable_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IterableSource(ResumableSource[IterableSourceConfig, IterableResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ITERABLE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Iterable rejected the API key. Make sure you're using a server-side API key from the "
                "matching data center (US or EU) and reconnect."
            ),
            "403 Client Error": (
                "The Iterable API key doesn't have permission for this endpoint. Grant the key access to "
                "the resources you're syncing and reconnect."
            ),
        }

    def get_schemas(
        self,
        config: IterableSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: IterableSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_iterable_credentials(config.api_key, config.region):
            return True, None

        return False, "Invalid Iterable API key for the selected data center"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[IterableResumeConfig]:
        return ResumableSourceManager[IterableResumeConfig](inputs, IterableResumeConfig)

    def source_for_pipeline(
        self,
        config: IterableSourceConfig,
        resumable_source_manager: ResumableSourceManager[IterableResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return iterable_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ITERABLE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Iterable",
            caption="""Enter your Iterable API key to pull your Iterable data into the PostHog Data warehouse.

Create a **server-side** API key with read permissions in your [Iterable integrations settings](https://app.iterable.com/settings/apiKeys). Client-side (Mobile/Browser/JWT) keys are not supported.

Make sure the data center below matches the one that issued your key (US or EU).""",
            iconPath="/static/services/iterable.png",
            docsUrl="https://posthog.com/docs/cdp/sources/iterable",
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Data center",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.iterable.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.iterable.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
