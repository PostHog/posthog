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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.eventee import (
    eventee_source,
    validate_credentials as validate_eventee_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EventeeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EventeeSource(SimpleSource[EventeeSourceConfig]):
    supported_versions = ("v1",)
    default_version = "v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EVENTEE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EVENTEE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Eventee",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Eventee API token to pull your event's content into the PostHog Data warehouse.

Generate a token in your Eventee admin dashboard under **Settings → Features**. The token is scoped to a single event, so connect one source per event you want to import.

All Eventee tables are full refresh only — the API exposes no incremental sync filter.""",
            iconPath="/static/services/eventee.png",
            docsUrl="https://posthog.com/docs/cdp/sources/eventee",
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
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or expired token surfaces as a 401 (`token_invalid`) when `fetch` calls
            # `raise_for_status()`. Retrying can never fix a credential problem. Match the stable
            # status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.eventee.com": "Your Eventee API token is invalid or has expired. Generate a new token in your Eventee admin dashboard (Settings → Features), then reconnect.",
            "403 Client Error: Forbidden for url: https://api.eventee.com": "Your Eventee API token does not have access to this event's data. Check the token in your Eventee admin dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: EventeeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is a snapshot with no server-side timestamp filter, so all are full refresh
        # only (no incremental/append).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Full refresh only — Eventee exposes no incremental sync filter",
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: EventeeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_eventee_credentials(config.api_key):
            return True, None

        return False, "Invalid Eventee API token"

    def source_for_pipeline(self, config: EventeeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return eventee_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
