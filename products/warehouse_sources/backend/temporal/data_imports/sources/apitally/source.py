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
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import (
    ApitallyResumeConfig,
    apitally_source,
    validate_credentials as validate_apitally_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.apitally import (
    ApitallySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ApitallySource(ResumableSource[ApitallySourceConfig, ApitallyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.apitally.io/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APITALLY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Apitally API key. Please generate a new key and reconnect.",
            "403 Client Error": "Your Apitally plan does not include API access. Upgrade to the Premium plan to enable it.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ApitallySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ApitallySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_apitally_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ApitallyResumeConfig]:
        return ResumableSourceManager[ApitallyResumeConfig](inputs, ApitallyResumeConfig)

    def source_for_pipeline(
        self,
        config: ApitallySourceConfig,
        resumable_source_manager: ResumableSourceManager[ApitallyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return apitally_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APITALLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Apitally",
            caption=(
                "Enter your Apitally API key to sync app, consumer, endpoint, traffic, and request "
                "log data into the PostHog Data warehouse.\n\n"
                "API access requires the Apitally Premium plan. Create a team-scoped API key in "
                "your Apitally team settings under **API keys**."
            ),
            iconPath="/static/services/apitally.png",
            docsUrl="https://posthog.com/docs/cdp/sources/apitally",
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
        )
