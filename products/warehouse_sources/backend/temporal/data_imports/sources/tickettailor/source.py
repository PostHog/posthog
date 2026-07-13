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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TicketTailorSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.settings import (
    ENDPOINTS,
    TICKET_TAILOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.tickettailor import (
    TicketTailorResumeConfig,
    tickettailor_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TicketTailorSource(ResumableSource[TicketTailorSourceConfig, TicketTailorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TICKETTAILOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TICKET_TAILOR,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Ticket Tailor",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Ticket Tailor API key to pull your event ticketing data into the PostHog Data warehouse.

You can create an API key under **Settings → API** in your [Ticket Tailor](https://www.tickettailor.com) box office. API keys are scoped to a single box office — connect one source per box office you want to sync.
""",
            iconPath="/static/services/tickettailor.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tickettailor",
            keywords=["tickets", "ticketing", "events", "box office"],
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Ticket Tailor answers invalid or deleted API keys with 403 (it reserves 401 for
        # malformed auth headers) — both are permanent credential failures.
        return {
            "401 Client Error: Unauthorized for url: https://api.tickettailor.com": "Your Ticket Tailor API key is invalid. Generate a new key under Settings → API in your box office, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.tickettailor.com": "Your Ticket Tailor API key is invalid, deleted, or does not have access to this data. Check the key under Settings → API in your box office, then reconnect.",
        }

    def get_schemas(
        self,
        config: TicketTailorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — see settings.py for why there is no reliable
        # incremental cursor to advance.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TicketTailorSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is box-office-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TicketTailorResumeConfig]:
        return ResumableSourceManager[TicketTailorResumeConfig](inputs, TicketTailorResumeConfig)

    def source_for_pipeline(
        self,
        config: TicketTailorSourceConfig,
        resumable_source_manager: ResumableSourceManager[TicketTailorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in TICKET_TAILOR_ENDPOINTS:
            raise ValueError(f"Unknown Ticket Tailor schema '{inputs.schema_name}'")

        return tickettailor_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
