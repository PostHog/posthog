from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.companycam import (
    CompanycamResumeConfig,
    companycam_source,
    validate_credentials as validate_companycam_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.companycam import (
    CompanycamSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CompanycamSource(ResumableSource[CompanycamSourceConfig, CompanycamResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.companycam.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COMPANYCAM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your CompanyCam API key is invalid or expired. "
            "Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url": "Your CompanyCam API key does not have permission "
            "to access this data.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CompanycamSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CompanycamSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_companycam_credentials(config.api_key, self.resolve_api_version(api_version)):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CompanycamResumeConfig]:
        return ResumableSourceManager[CompanycamResumeConfig](inputs, CompanycamResumeConfig)

    def source_for_pipeline(
        self,
        config: CompanycamSourceConfig,
        resumable_source_manager: ResumableSourceManager[CompanycamResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return companycam_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COMPANYCAM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="CompanyCam",
            caption="Sync projects, photos, videos, and team data from your CompanyCam account. "
            "Generate an API key from your [CompanyCam account settings](https://docs.companycam.com/reference/authentication).",
            docsUrl="https://posthog.com/docs/cdp/sources/companycam",
            releaseStatus=ReleaseStatus.ALPHA,
            iconPath="/static/services/companycam.png",
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
