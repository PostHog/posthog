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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RampSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.ramp import (
    RampResumeConfig,
    ramp_source,
    validate_credentials as validate_ramp_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RampSource(ResumableSource[RampSourceConfig, RampResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.ramp.com/developer-api/v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAMP

    @property
    def connection_host_fields(self) -> list[str]:
        # ``environment`` picks api.ramp.com vs demo-api.ramp.com, so changing it retargets where the
        # stored client secret is sent — require re-entering secrets when it changes.
        return ["environment"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.ramp.com/developer/v1/token": "Ramp authentication failed. Please check your client ID and client secret.",
            "401 Client Error: Unauthorized for url: https://demo-api.ramp.com/developer/v1/token": "Ramp authentication failed. Please check your client ID and client secret (and that they match the selected environment).",
            "400 Client Error: Bad Request for url: https://api.ramp.com/developer/v1/token": "Ramp rejected the token request. Please check that your developer app has the required read scopes granted.",
            "400 Client Error: Bad Request for url: https://demo-api.ramp.com/developer/v1/token": "Ramp rejected the token request. Please check that your developer app has the required read scopes granted.",
            "403 Client Error: Forbidden for url: https://api.ramp.com": "Ramp denied access. Please check that your developer app has the read scope for this dataset.",
            "403 Client Error: Forbidden for url: https://demo-api.ramp.com": "Ramp denied access. Please check that your developer app has the read scope for this dataset.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RAMP,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Ramp",
            caption="""Connect your Ramp account to pull your spend data into the PostHog Data warehouse.

A Ramp admin can create a developer app under Settings > Developer API. Grant it the `transactions:read`, `reimbursements:read`, `users:read`, `cards:read`, and `departments:read` scopes (scopes are fixed at app creation) and enable client credentials, then enter the app's client ID and secret here.""",
            iconPath="/static/services/ramp.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ramp",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox (demo)", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ramp_id_...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="ramp_sec_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: RampSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: RampSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_ramp_credentials(config.environment, config.client_id, config.client_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RampResumeConfig]:
        return ResumableSourceManager[RampResumeConfig](inputs, RampResumeConfig)

    def source_for_pipeline(
        self,
        config: RampSourceConfig,
        resumable_source_manager: ResumableSourceManager[RampResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ramp_source(
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
