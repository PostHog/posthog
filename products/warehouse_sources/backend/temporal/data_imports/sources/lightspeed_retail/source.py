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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    LightspeedRetailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail import (
    LightspeedRetailResumeConfig,
    lightspeed_retail_source,
    validate_credentials as validate_lightspeed_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LightspeedRetailSource(ResumableSource[LightspeedRetailSourceConfig, LightspeedRetailResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIGHTSPEEDRETAIL

    @property
    def connection_host_fields(self) -> list[str]:
        # `domain_prefix` determines the host the stored personal token is sent
        # to; retargeting it must re-require the token.
        return ["domain_prefix"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Lightspeed Retail authentication failed. Please check your personal token and store domain prefix.",
            "403 Client Error: Forbidden for url": "Lightspeed Retail denied access. Please check that your personal token has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LIGHTSPEED_RETAIL,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            keywords=["lightspeed"],
            label="Lightspeed Retail",
            caption="""Enter your Lightspeed Retail (X-Series) credentials to pull your point-of-sale data into the PostHog Data warehouse.

Your domain prefix is the first part of your store URL — for `mystore.retail.lightspeed.app` enter `mystore`. An admin can create a personal token in Setup > Personal Tokens (available on the Plus plan and above).""",
            iconPath="/static/services/lightspeed_retail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lightspeed-retail",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="domain_prefix",
                        label="Domain prefix",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mystore",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal token",
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
        config: LightspeedRetailSourceConfig,
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
        self, config: LightspeedRetailSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_lightspeed_credentials(config.domain_prefix, config.api_token):
            return True, None

        return False, "Invalid Lightspeed Retail credentials"

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[LightspeedRetailResumeConfig]:
        return ResumableSourceManager[LightspeedRetailResumeConfig](inputs, LightspeedRetailResumeConfig)

    def source_for_pipeline(
        self,
        config: LightspeedRetailSourceConfig,
        resumable_source_manager: ResumableSourceManager[LightspeedRetailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lightspeed_retail_source(
            domain_prefix=config.domain_prefix,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
