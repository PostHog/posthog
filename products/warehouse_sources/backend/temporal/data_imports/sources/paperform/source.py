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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PaperformSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.paperform import (
    PaperformResumeConfig,
    paperform_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import (
    INCREMENTAL_FIELDS,
    PAPERFORM_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PaperformSource(ResumableSource[PaperformSourceConfig, PaperformResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAPERFORM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAPERFORM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Paperform",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Paperform API key to pull your forms and submissions data into the PostHog Data warehouse.

You can create an API key under **Account → Developer** in [Paperform](https://paperform.co). API access requires a Pro, Business, or Agency plan, and the `spaces` table additionally requires a Business or Agency plan.
""",
            iconPath="/static/services/paperform.png",
            docsUrl="https://posthog.com/docs/cdp/sources/paperform",
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.paperform.co": "Your Paperform API key is invalid or has been revoked. Generate a new key under Account → Developer, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.paperform.co": "Your Paperform plan does not include access to this data. API access requires a Pro, Business, or Agency plan, and the spaces table requires a Business or Agency plan.",
        }

    def get_schemas(
        self,
        config: PaperformSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = []
        for endpoint in PAPERFORM_ENDPOINTS:
            if names is not None and endpoint not in names:
                continue
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            supports_incremental = bool(incremental_fields)
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=incremental_fields,
                )
            )
        return schemas

    def validate_credentials(
        self, config: PaperformSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates the credential for every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PaperformResumeConfig]:
        return ResumableSourceManager[PaperformResumeConfig](inputs, PaperformResumeConfig)

    def source_for_pipeline(
        self,
        config: PaperformSourceConfig,
        resumable_source_manager: ResumableSourceManager[PaperformResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PAPERFORM_ENDPOINTS:
            raise ValueError(f"Unknown Paperform schema '{inputs.schema_name}'")

        return paperform_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
