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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SolarwindsServiceDeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SOLARWINDS_SERVICE_DESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.solarwinds_service_desk import (
    SOLARWINDS_SERVICE_DESK_HOSTS,
    SolarwindsServiceDeskResumeConfig,
    solarwinds_service_desk_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SolarwindsServiceDeskSource(
    ResumableSource[SolarwindsServiceDeskSourceConfig, SolarwindsServiceDeskResumeConfig]
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SOLARWINDSSERVICEDESK

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to the host derived from `region`, so changing the region must
        # re-require the token rather than reusing it against a different host.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SOLARWINDS_SERVICE_DESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="SolarWinds Service Desk",
            keywords=["samanage", "swsd", "solarwinds", "itsm", "service desk"],
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden for now: the implementation follows the public API docs but its
            # end-to-end sync behavior hasn't been exercised against a live account yet.
            unreleasedSource=True,
            caption="""Enter your SolarWinds Service Desk JSON web token to pull your service desk data into the PostHog Data warehouse.

You can generate a token in SolarWinds Service Desk under **Setup → Users & Access → Users** — open the user and use **Actions → Generate JSON Web Token**. The token inherits that user's role, so it needs read access to the records you want to sync, and requests stop working if that user is ever disabled.

SolarWinds Service Desk runs independent regional stacks that do not share data — pick the region your account is on.""",
            iconPath="/static/services/solarwinds_service_desk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/solarwinds-service-desk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.samanage.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (apieu.samanage.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="APJ (apiau.samanage.com)", value="au"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="JSON web token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        invalid_token = (
            "Your SolarWinds Service Desk token is invalid or its user has been disabled. "
            "Generate a new JSON web token and reconnect."
        )
        missing_role = (
            "Your SolarWinds Service Desk token does not have permission to read this data. "
            "Check the token owner's role, then reconnect."
        )
        errors: dict[str, str | None] = {}
        for host in SOLARWINDS_SERVICE_DESK_HOSTS.values():
            errors[f"401 Client Error: Unauthorized for url: {host}"] = invalid_token
            errors[f"403 Client Error: Forbidden for url: {host}"] = missing_role
        return errors

    def get_schemas(
        self,
        config: SolarwindsServiceDeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SolarwindsServiceDeskSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # At source-create only the token is probed (a 403 there can just mean the token's role
        # doesn't cover the probe resource); with a schema_name we probe that endpoint's own path.
        endpoint = SOLARWINDS_SERVICE_DESK_ENDPOINTS.get(schema_name) if schema_name else None
        return validate_credentials(config.region, config.api_token, endpoint.path if endpoint else None)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[SolarwindsServiceDeskResumeConfig]:
        return ResumableSourceManager[SolarwindsServiceDeskResumeConfig](inputs, SolarwindsServiceDeskResumeConfig)

    def source_for_pipeline(
        self,
        config: SolarwindsServiceDeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[SolarwindsServiceDeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SOLARWINDS_SERVICE_DESK_ENDPOINTS:
            raise ValueError(f"Unknown SolarWinds Service Desk schema '{inputs.schema_name}'")

        return solarwinds_service_desk_source(
            region=config.region,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
