from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.amplitude import (
    AmplitudeResumeConfig,
    amplitude_source,
    validate_credentials as validate_amplitude_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    AMPLITUDE_ENDPOINTS,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AmplitudeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmplitudeSource(ResumableSource[AmplitudeSourceConfig, AmplitudeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMPLITUDE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Amplitude rejected the credentials. Generate a fresh API key and secret key in Amplitude "
            "(Settings → Organization settings → Projects) and reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "403 Client Error: Forbidden": message,
            "Invalid API Key": message,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmplitudeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_append,
                incremental_fields=endpoint.incremental_fields,
                description="Only syncs the last 30 days on initial sync" if endpoint.name == EVENTS_ENDPOINT else None,
            )
            for endpoint in AMPLITUDE_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AmplitudeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_amplitude_credentials(config.api_key, config.secret_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AmplitudeResumeConfig]:
        return ResumableSourceManager[AmplitudeResumeConfig](inputs, AmplitudeResumeConfig)

    def source_for_pipeline(
        self,
        config: AmplitudeSourceConfig,
        resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amplitude_source(
            api_key=config.api_key,
            secret_key=config.secret_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AMPLITUDE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Amplitude",
            caption=(
                "Connect Amplitude with your project's **API key** and **secret key**, found in Amplitude under "
                "**Settings → Organization settings → Projects**. These authenticate the Export API (raw events), "
                "the Cohorts API, and the Annotations API.\n\n"
                "The events stream uses Amplitude's Export API, which enforces a ~2 hour data latency and only "
                "syncs the last 30 days on the initial sync."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/amplitude",
            iconPath="/static/services/amplitude.png",
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
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (amplitude.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (analytics.eu.amplitude.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
