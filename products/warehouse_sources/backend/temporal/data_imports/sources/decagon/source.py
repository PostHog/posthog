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
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import (
    DecagonResumeConfig,
    decagon_source,
    validate_credentials as validate_decagon_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DecagonSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DecagonSource(ResumableSource[DecagonSourceConfig, DecagonResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DECAGON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DECAGON,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Decagon",
            caption="""Enter a Decagon API key to pull your Decagon conversations into the PostHog Data warehouse.

You can find your API key on the **Developer** page of the [Decagon dashboard](https://decagon.ai/).
""",
            iconPath="/static/services/decagon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/decagon",
            keywords=["ai agents", "customer support", "conversations", "csat"],
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
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Decagon rejected the API key. Generate a new key on the Developer page of the "
                "Decagon dashboard and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The Decagon API key does not have access to the conversation export. Check the key "
                "on the Developer page of the Decagon dashboard and reconnect."
            ),
        }

    def get_schemas(
        self,
        config: DecagonSourceConfig,
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
        self, config: DecagonSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_decagon_credentials(config.api_key):
            return True, None

        return False, "Invalid Decagon API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DecagonResumeConfig]:
        return ResumableSourceManager[DecagonResumeConfig](inputs, DecagonResumeConfig)

    def source_for_pipeline(
        self,
        config: DecagonSourceConfig,
        resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return decagon_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
