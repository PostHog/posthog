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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PretixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.pretix import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    PretixResumeConfig,
    pretix_source,
    validate_credentials as validate_pretix_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRETIX_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PretixSource(ResumableSource[PretixSourceConfig, PretixResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRETIX

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API token is sent; retargeting it must re-require the token.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PRETIX,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Pretix",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["ticketing", "events", "tickets"],
            caption="""Enter your pretix API token to pull your event ticketing data into the PostHog Data warehouse.

You can create a team API token in pretix under **Organizer settings → Teams → your team → Create API token**. The token is scoped to one organizer; enter that organizer's short name (slug) below. The token's team needs read permission for the resources you want to sync (for example *Can view orders* for orders and invoices, *Can view vouchers* for vouchers).

Self-hosted users should set the API URL to their own pretix host (for example `https://tickets.example.com`). Leave it blank to use the hosted pretix (`https://pretix.eu`).""",
            iconPath="/static/services/pretix.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pretix",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organizer",
                        label="Organizer short name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-organizer",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://pretix.eu",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pretix.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your pretix API token is invalid or has been revoked. Create a new team API token in pretix and reconnect.",
            "403 Client Error": "Your pretix API token does not have permission for this data. Check the token's team permissions (for example 'Can view orders') and try again.",
            HOST_NOT_ALLOWED_ERROR: "The pretix API URL is not allowed. Please use a publicly reachable host.",
            HTTP_NOT_ALLOWED_ERROR: "The pretix API URL must use HTTPS. Please update the API URL to use https://.",
        }

    def get_schemas(
        self,
        config: PretixSourceConfig,
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

    def validate_credentials(
        self, config: PretixSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_pretix_credentials(config.api_token, config.organizer, config.base_url, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PretixResumeConfig]:
        return ResumableSourceManager[PretixResumeConfig](inputs, PretixResumeConfig)

    def source_for_pipeline(
        self,
        config: PretixSourceConfig,
        resumable_source_manager: ResumableSourceManager[PretixResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PRETIX_ENDPOINTS:
            raise ValueError(f"Unknown pretix schema '{inputs.schema_name}'")

        return pretix_source(
            api_token=config.api_token,
            organizer=config.organizer,
            base_url=config.base_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
