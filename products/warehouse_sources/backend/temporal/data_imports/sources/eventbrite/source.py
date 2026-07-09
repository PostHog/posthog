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
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.eventbrite import (
    EventbriteResumeConfig,
    eventbrite_source,
    validate_credentials as validate_eventbrite_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EventbriteSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EventbriteSource(ResumableSource[EventbriteSourceConfig, EventbriteResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EVENTBRITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EVENTBRITE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Eventbrite",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Eventbrite private token to automatically pull your Eventbrite data into the PostHog Data warehouse.

You can create a private token under your [Eventbrite account settings](https://www.eventbrite.com/account-settings/apps) on the **API Keys** page (the **Private token** field of your API key).

The token needs read access to your organizations, events, orders, and attendees.
""",
            iconPath="/static/services/eventbrite.png",
            docsUrl="https://posthog.com/docs/cdp/sources/eventbrite",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Private token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Eventbrite private token",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: EventbriteSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_ENDPOINTS,
                supports_append=endpoint in INCREMENTAL_ENDPOINTS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.eventbrite.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://www.eventbriteapi.com": "Your Eventbrite private token is invalid or has been revoked. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://www.eventbriteapi.com": "Your Eventbrite private token does not have permission to access this resource. Please check the token's permissions and try again.",
        }

    def validate_credentials(
        self, config: EventbriteSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_eventbrite_credentials(config.api_token):
            return True, None

        return False, "Invalid Eventbrite private token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EventbriteResumeConfig]:
        return ResumableSourceManager[EventbriteResumeConfig](inputs, EventbriteResumeConfig)

    def source_for_pipeline(
        self,
        config: EventbriteSourceConfig,
        resumable_source_manager: ResumableSourceManager[EventbriteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return eventbrite_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
