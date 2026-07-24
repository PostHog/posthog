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
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn import (
    AutumnResumeConfig,
    autumn_source,
    validate_credentials as validate_autumn_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.autumn import AutumnSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AutumnSource(ResumableSource[AutumnSourceConfig, AutumnResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2.3.0",)
    default_version = "2.3.0"
    api_docs_url = "https://docs.useautumn.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AUTUMN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.useautumn.com": (
                "Your Autumn secret key is invalid or was revoked. Generate a new secret key in the "
                "Autumn dashboard and update the source."
            ),
            "403 Client Error: Forbidden for url: https://api.useautumn.com": (
                "Your Autumn secret key does not have access to this data. Check the key's environment "
                "in the Autumn dashboard."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AutumnSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: AutumnSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_autumn_credentials(config.api_key, self.default_version)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AutumnResumeConfig]:
        return ResumableSourceManager[AutumnResumeConfig](inputs, AutumnResumeConfig)

    def source_for_pipeline(
        self,
        config: AutumnSourceConfig,
        resumable_source_manager: ResumableSourceManager[AutumnResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return autumn_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
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
            name=SchemaExternalDataSourceType.AUTUMN,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Autumn",
            caption=(
                "Sync customers, usage events, features, plans, entities, invoices, and rewards from Autumn. "
                "Create a secret key (`am_sk_...`) in the Autumn dashboard under Developer settings. "
                "Sandbox and production have separate keys, so use the key for the environment you want to sync."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/autumn",
            iconPath="/static/services/autumn.png",
            keywords=["billing", "subscriptions", "useautumn"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="am_sk_...",
                        secret=True,
                    ),
                ],
            ),
        )
