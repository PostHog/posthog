from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.survicate import (
    SurvicateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.survicate import (
    SurvicateResumeConfig,
    survicate_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SurvicateSource(ResumableSource[SurvicateSourceConfig, SurvicateResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.survicate.com/data-export/migration-v1-v2/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SURVICATE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERRORS[401],
            "403 Client Error": AUTH_ERRORS[403],
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SurvicateSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"responses"})

    def validate_credentials(
        self,
        config: SurvicateSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SurvicateResumeConfig]:
        return ResumableSourceManager(inputs, SurvicateResumeConfig)

    def source_for_pipeline(
        self,
        config: SurvicateSourceConfig,
        resumable_source_manager: ResumableSourceManager[SurvicateResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return survicate_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SURVICATE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Survicate",
            caption="Find your API key in Survicate under Settings > Organization > Access Keys. "
            "Your plan must include the Data Export API.",
            docsUrl="https://developers.survicate.com/data-export/setup/",
            iconPath="/static/services/survicate.png",
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
                    SourceFieldInputConfig(
                        name="attribute_names",
                        label="Attribute names",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        secret=False,
                        placeholder="order_id, store",
                        caption="Separate names with commas. Leave this empty to exclude response and respondent attributes.",
                    ),
                ],
            ),
        )
