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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZuoraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.zuora import (
    ZuoraResumeConfig,
    validate_credentials as validate_zuora_credentials,
    zuora_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZuoraSource(ResumableSource[ZuoraSourceConfig, ZuoraResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZUORA

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://rest.": "Zuora rejected the request. If this occurs while connecting, check your client ID and client secret (and that they match the selected environment).",
            "401 Client Error: Unauthorized for url: https://rest.": "Zuora authentication failed. Please check your client ID and client secret (and that they match the selected environment).",
            "403 Client Error: Forbidden for url: https://rest.": "Zuora denied access. Please check that the OAuth client's user has permission for this object.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZUORA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Zuora",
            caption="""Connect your Zuora tenant to pull your subscription billing data into the PostHog Data warehouse.

A Zuora admin can create an OAuth client under Settings > Administration > Manage Users (the client inherits the user's permissions). Pick the environment that matches your tenant — credentials only work against their own environment.""",
            iconPath="/static/services/zuora.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zuora",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="us_production",
                        options=[
                            SourceFieldSelectConfigOption(label="US Production", value="us_production"),
                            SourceFieldSelectConfigOption(label="US API Sandbox", value="us_api_sandbox"),
                            SourceFieldSelectConfigOption(label="US Cloud Production", value="us_cloud_production"),
                            SourceFieldSelectConfigOption(label="US Cloud Sandbox", value="us_cloud_sandbox"),
                            SourceFieldSelectConfigOption(label="EU Production", value="eu_production"),
                            SourceFieldSelectConfigOption(label="EU Sandbox", value="eu_sandbox"),
                            SourceFieldSelectConfigOption(label="Central Sandbox", value="central_sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: ZuoraSourceConfig,
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
        self, config: ZuoraSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_zuora_credentials(config.environment, config.client_id, config.client_secret):
            return True, None

        return False, "Invalid Zuora credentials. Check the client ID, client secret, and environment."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZuoraResumeConfig]:
        return ResumableSourceManager[ZuoraResumeConfig](inputs, ZuoraResumeConfig)

    def source_for_pipeline(
        self,
        config: ZuoraSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZuoraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zuora_source(
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
