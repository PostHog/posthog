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
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.cloudbeds import (
    CloudbedsResumeConfig,
    cloudbeds_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.settings import (
    CLOUDBEDS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CloudbedsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudbedsSource(ResumableSource[CloudbedsSourceConfig, CloudbedsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog - safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDBEDS

    @property
    def connection_host_fields(self) -> list[str]:
        # `property_id` scopes which property the stored API key reads from; retargeting it must
        # re-require the key so a group-level credential can't be pointed at another property.
        return ["property_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDBEDS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Cloudbeds",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Cloudbeds API key to pull your properties, reservations, guests, rooms, room types, and transactions into the PostHog Data warehouse.

You can create an API key under **Settings → API credentials** in [Cloudbeds](https://hotels.cloudbeds.com). Note that Cloudbeds API keys expire after 30 days of inactivity, so a key that has not been used recently may need to be regenerated.

If your account manages multiple properties, enter the ID of the property you want to sync - group-level credentials require it to scope reads to a single property.
""",
            iconPath="/static/services/cloudbeds.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudbeds",
            keywords=["pms", "hotel", "hospitality"],
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
                        name="property_id",
                        label="Property ID (required for multi-property accounts)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.cloudbeds.com": "Your Cloudbeds API key is invalid or has expired (keys expire after 30 days of inactivity). Generate a new key under Settings → API credentials, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.cloudbeds.com": "Your Cloudbeds credentials do not have access to this data. Check the credential's permission scopes, then reconnect.",
        }

    def get_schemas(
        self,
        config: CloudbedsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only for now - see the note in settings.py about the
        # unverified `modifiedSince` filter on getReservations.
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
        self, config: CloudbedsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # One probe validates the token itself; per-endpoint OAuth scopes surface at sync time via
        # get_non_retryable_errors.
        return validate_credentials(config.api_key, config.property_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloudbedsResumeConfig]:
        return ResumableSourceManager[CloudbedsResumeConfig](inputs, CloudbedsResumeConfig)

    def source_for_pipeline(
        self,
        config: CloudbedsSourceConfig,
        resumable_source_manager: ResumableSourceManager[CloudbedsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in CLOUDBEDS_ENDPOINTS:
            raise ValueError(f"Unknown Cloudbeds schema '{inputs.schema_name}'")

        return cloudbeds_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            property_id=config.property_id,
        )
