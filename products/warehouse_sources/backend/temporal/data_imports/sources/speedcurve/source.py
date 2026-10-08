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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.speedcurve import (
    SpeedcurveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.speedcurve import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    SpeedcurveResumeConfig,
    speedcurve_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SpeedcurveSource(ResumableSource[SpeedcurveSourceConfig, SpeedcurveResumeConfig]):
    lists_tables_without_credentials = True
    # SpeedCurve v2 remains beta: https://support.speedcurve.com/reference/getting-started-with-api-v2
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://support.speedcurve.com/reference/getting-started"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPEEDCURVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPEEDCURVE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="SpeedCurve",
            iconPath="/static/services/speedcurve.png",
            caption="Find your API key in SpeedCurve under **Admin > Teams**. An organization admin can access this page.",
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
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SpeedcurveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)
        for schema in schemas:
            schema.detected_primary_keys = list(ENDPOINTS[schema.name].primary_keys)
            if schema.supports_incremental:
                # Recent tests can still be queued, and deployment notes can change after creation.
                schema.default_incremental_lookback_seconds = INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: SpeedcurveSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SpeedcurveResumeConfig]:
        return ResumableSourceManager(inputs, SpeedcurveResumeConfig)

    def source_for_pipeline(
        self,
        config: SpeedcurveSourceConfig,
        resumable_source_manager: ResumableSourceManager[SpeedcurveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return speedcurve_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
