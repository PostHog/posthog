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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstatusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.instatus import (
    InstatusResumeConfig,
    instatus_source,
    validate_credentials as validate_instatus_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InstatusSource(ResumableSource[InstatusSourceConfig, InstatusResumeConfig]):
    # get_schemas iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in the public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSTATUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSTATUS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Instatus",
            caption=(
                "Sync your Instatus status pages, components, incidents, maintenances and more. "
                "Create an API key under **[Developer settings](https://dashboard.instatus.com/developer)** "
                "and paste it below. The key grants access to every status page in your account."
            ),
            iconPath="/static/services/instatus.png",
            docsUrl="https://posthog.com/docs/cdp/sources/instatus",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Instatus API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Instatus API key. Please check your API key and reconnect.",
            "403 Client Error": "Your Instatus API key lacks the required permissions. Please check the key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: InstatusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Instatus has no server-side updated_after/since filter on any list endpoint, so
                # every schema is full-refresh only.
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InstatusSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_instatus_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InstatusResumeConfig]:
        return ResumableSourceManager[InstatusResumeConfig](inputs, InstatusResumeConfig)

    def source_for_pipeline(
        self,
        config: InstatusSourceConfig,
        resumable_source_manager: ResumableSourceManager[InstatusResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return instatus_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
