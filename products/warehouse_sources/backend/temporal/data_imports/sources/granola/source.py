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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GranolaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola import (
    GranolaResumeConfig,
    granola_source,
    validate_credentials as validate_granola_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GranolaSource(ResumableSource[GranolaSourceConfig, GranolaResumeConfig]):
    api_docs_url = "https://docs.granola.ai"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GRANOLA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GRANOLA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Granola",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Granola API key to pull your meeting notes into the PostHog Data warehouse.

API access requires a **Business** plan or higher. Create a key (prefixed `grn_`) in the Granola desktop app under **Settings → Connectors → API keys**.

When creating the key, grant the access scopes for the data you want to sync:
- **Personal notes**
- **Public notes**

Only notes with a generated AI summary and transcript are returned by the API.
""",
            iconPath="/static/services/granola.png",
            docsUrl="https://docs.granola.ai/introduction",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="grn_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.granola.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GranolaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None
                and len(INCREMENTAL_FIELDS[endpoint]) > 0,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None and len(INCREMENTAL_FIELDS[endpoint]) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GranolaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_granola_credentials(config.api_key, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Granola API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden": "Your Granola API key does not have the required access scope. Please check the key's scopes and reconnect.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GranolaResumeConfig]:
        return ResumableSourceManager[GranolaResumeConfig](inputs, GranolaResumeConfig)

    def source_for_pipeline(
        self,
        config: GranolaSourceConfig,
        resumable_source_manager: ResumableSourceManager[GranolaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return granola_source(
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
