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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hyros import HyrosSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.hyros import (
    HyrosResumeConfig,
    hyros_source,
    validate_credentials as validate_hyros_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HyrosSource(ResumableSource[HyrosSourceConfig, HyrosResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1.0",)
    default_version = "v1.0"
    api_docs_url = "https://api-docs.hyros.com"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HYROS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": (
                "Your Hyros API key is invalid. Copy a fresh key from Hyros under Settings > Profile and reconnect."
            ),
            "403 Client Error: Forbidden for url": (
                "Your Hyros API key doesn't have the role required for this table. "
                "Grant the missing role in Hyros and try again."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HyrosSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HyrosSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status = validate_hyros_credentials(config.api_key)
        if ok:
            return True, None
        return (
            False,
            "Invalid Hyros API key. Copy the key from Hyros under Settings > Profile and try again.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HyrosResumeConfig]:
        return ResumableSourceManager[HyrosResumeConfig](inputs, HyrosResumeConfig)

    def source_for_pipeline(
        self,
        config: HyrosSourceConfig,
        resumable_source_manager: ResumableSourceManager[HyrosResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hyros_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HYROS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["ad attribution", "ad tracking", "roas", "call tracking"],
            label="Hyros",
            releaseStatus=ReleaseStatus.ALPHA,
            docsUrl="https://posthog.com/docs/cdp/sources/hyros",
            iconPath="/static/services/hyros.png",
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
                        caption="Find this in Hyros under Settings > Profile.",
                    ),
                ],
            ),
        )
