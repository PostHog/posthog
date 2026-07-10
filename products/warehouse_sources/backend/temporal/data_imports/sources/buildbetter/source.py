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
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter import (
    BuildBetterResumeConfig,
    buildbetter_source,
    validate_credentials as validate_buildbetter_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BuildBetterSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuildBetterSource(ResumableSource[BuildBetterSourceConfig, BuildBetterResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.buildbetter.app/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUILDBETTER

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "BuildBetter authentication failed. Please check your API key.",
            "403 Client Error": "BuildBetter access forbidden. Please check your API key permissions.",
            "Authentication hook unauthorized this request": "BuildBetter authentication failed. Please check your API key.",
        }

    def get_schemas(
        self,
        config: BuildBetterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BuildBetterSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_buildbetter_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BuildBetterResumeConfig]:
        return ResumableSourceManager[BuildBetterResumeConfig](inputs, BuildBetterResumeConfig)

    def source_for_pipeline(
        self,
        config: BuildBetterSourceConfig,
        resumable_source_manager: ResumableSourceManager[BuildBetterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        incremental_field_last_value = None
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            incremental_field_last_value = str(inputs.db_incremental_field_last_value)

        return buildbetter_source(
            api_key=config.api_key,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_last_value=incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUILD_BETTER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="BuildBetter",
            releaseStatus=ReleaseStatus.GA,
            caption="Connect your BuildBetter workspace to sync interviews, extractions, persons, and companies.",
            iconPath="/static/services/buildbetter.png",
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
