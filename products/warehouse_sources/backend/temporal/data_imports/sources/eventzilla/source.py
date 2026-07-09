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
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.eventzilla import (
    EventzillaResumeConfig,
    eventzilla_source,
    validate_credentials as validate_eventzilla_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.settings import (
    ENDPOINTS,
    EVENTZILLA_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EventzillaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EventzillaSource(ResumableSource[EventzillaSourceConfig, EventzillaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EVENTZILLA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EVENTZILLA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Eventzilla",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Eventzilla API key to automatically pull your Eventzilla data into the PostHog Data warehouse.

You can generate an API key in your Eventzilla account under **Settings > App Management**.""",
            iconPath="/static/services/eventzilla.png",
            docsUrl="https://posthog.com/docs/cdp/sources/eventzilla",
            unreleasedSource=True,
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Eventzilla returns 401/403 for an invalid, revoked, or unauthorized API key. Retrying
            # can never satisfy a credential problem, so stop the sync. Match the stable status text
            # and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://www.eventzillaapi.net": "Your Eventzilla API key is invalid or has been revoked. Generate a new key under Settings > App Management, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.eventzillaapi.net": "Your Eventzilla API key is not authorized to access this data. Check the key under Settings > App Management, then reconnect.",
        }

    def get_schemas(
        self,
        config: EventzillaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if EVENTZILLA_ENDPOINTS[endpoint].fan_out_over_events:
                return "Fetched per event by walking every event. Full refresh only"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = EVENTZILLA_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Eventzilla exposes no server-side updated-since filter, so every table is full
                # refresh only — no incremental or append modes.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: EventzillaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_eventzilla_credentials(config.api_key):
            return True, None

        return False, "Invalid Eventzilla API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EventzillaResumeConfig]:
        return ResumableSourceManager[EventzillaResumeConfig](inputs, EventzillaResumeConfig)

    def source_for_pipeline(
        self,
        config: EventzillaSourceConfig,
        resumable_source_manager: ResumableSourceManager[EventzillaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return eventzilla_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
