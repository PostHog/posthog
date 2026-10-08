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
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.gcore import (
    GcoreCheckpoint,
    gcore_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    STATISTICS_METRICS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcore import GcoreSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcoreSource(ResumableSource[GcoreSourceConfig, GcoreCheckpoint]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.gcore.com/api-reference/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCORE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCORE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Gcore",
            iconPath="/static/services/gcore.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Create an API token in the Gcore Customer Portal under API tokens. "
            "Give the token permission to read CDN data. "
            "Statistics contain hourly values for completed hours, with up to 365 days of history.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    )
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERRORS[401],
            "403 Client Error": AUTH_ERRORS[403],
            "HTTP 401": AUTH_ERRORS[401],
            "HTTP 403": AUTH_ERRORS[403],
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GcoreSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=STATISTICS_METRICS)
        for schema in schemas:
            if schema.name in STATISTICS_METRICS:
                schema.default_incremental_lookback_seconds = 2 * 24 * 60 * 60
        return schemas

    def validate_credentials(
        self,
        config: GcoreSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GcoreCheckpoint]:
        return ResumableSourceManager(inputs, GcoreCheckpoint)

    def source_for_pipeline(
        self,
        config: GcoreSourceConfig,
        resumable_source_manager: ResumableSourceManager[GcoreCheckpoint],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gcore_source(config.api_key, inputs, resumable_source_manager)
