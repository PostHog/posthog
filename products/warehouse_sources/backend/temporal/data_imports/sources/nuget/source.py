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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NugetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.nuget import (
    PACKAGE_NOT_FOUND_PREFIX,
    NugetResumeConfig,
    nuget_source,
    validate_nuget_connection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.settings import (
    INCREMENTAL_FIELDS,
    NUGET_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NugetSource(ResumableSource[NugetSourceConfig, NugetResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NUGET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NUGET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="NuGet",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["dotnet", ".net", "csharp", "package registry"],
            caption="""Track adoption of .NET libraries over time: package metadata, per-version download counts, and publish/delete events for the NuGet packages you care about.

The public NuGet V3 API allows anonymous read access, so no API key is needed. Enter the package IDs you want to track, separated by commas or new lines — e.g. `Newtonsoft.Json, Serilog`.
""",
            iconPath="/static/services/nuget.png",
            docsUrl="https://posthog.com/docs/cdp/sources/nuget",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="package_ids",
                        label="Package IDs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="Newtonsoft.Json, Serilog, Microsoft.Extensions.Logging",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Raised when a configured package id has no registration index (404). Retrying can never
            # make a nonexistent package appear, so stop the sync with an actionable message.
            PACKAGE_NOT_FOUND_PREFIX: "One of the configured package IDs does not exist on NuGet. Check the spelling of your package IDs and update the source.",
        }

    def get_schemas(
        self,
        config: NugetSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                # Catalog leaves are immutable events, so append-only sync is also safe there.
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )
            for endpoint, endpoint_config in NUGET_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NugetSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            return validate_nuget_connection(config.package_ids)
        except ValueError as e:
            return False, str(e)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NugetResumeConfig]:
        return ResumableSourceManager[NugetResumeConfig](inputs, NugetResumeConfig)

    def source_for_pipeline(
        self,
        config: NugetSourceConfig,
        resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return nuget_source(
            package_ids=config.package_ids,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
