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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotio import SpotIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io import (
    SpotIoResumeConfig,
    spot_io_source,
    validate_credentials as validate_spot_io_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SpotIoSource(ResumableSource[SpotIoSourceConfig, SpotIoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.flexera.com/spot/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPOTIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Spot by Flexera authentication failed. Please check your API token.",
            "403 Client Error": "Spot by Flexera API token does not have the required permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SpotIoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SpotIoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_spot_io_credentials(config.api_token, config.account_id or None)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SpotIoResumeConfig]:
        return ResumableSourceManager[SpotIoResumeConfig](inputs, SpotIoResumeConfig)

    def source_for_pipeline(
        self,
        config: SpotIoSourceConfig,
        resumable_source_manager: ResumableSourceManager[SpotIoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return spot_io_source(
            api_token=config.api_token,
            account_id=config.account_id or None,
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
            name=SchemaExternalDataSourceType.SPOT_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Spot by Flexera (Spotinst)",
            caption="Import Elastigroup and Ocean cloud cost optimization data from your Spot by Flexera account.",
            docsUrl="https://posthog.com/docs/cdp/sources/spot-io",
            iconPath="/static/services/spot_io.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["spot", "spotinst", "finops", "cloud cost", "kubernetes"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="act-123abcd",
                        secret=False,
                    ),
                ],
            ),
        )
