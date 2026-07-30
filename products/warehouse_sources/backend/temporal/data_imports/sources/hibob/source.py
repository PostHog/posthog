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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HiBobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob import (
    hibob_source,
    validate_credentials as validate_hibob_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HiBobSource(SimpleSource[HiBobSourceConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://apidocs.hibob.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HIBOB

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Repeated 401/403s trip HiBob's WAF (5-minute IP block), so failing
        # fast on auth errors matters more than usual here.
        return {
            "401 Client Error: Unauthorized for url: https://api.hibob.com": "HiBob authentication failed. Please check your Service User ID and token (legacy API tokens were discontinued — only Service Users work).",
            "403 Client Error: Forbidden for url: https://api.hibob.com": "HiBob denied access. Please add your Service User to a permission group with access to this data category.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HI_BOB,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            keywords=["bob"],
            label="HiBob",
            caption="""Enter your HiBob Service User credentials to pull your Bob HR data into the PostHog Data warehouse.

Create a Service User in Bob under Settings > Integrations > Automation > Service Users, then add it to a permission group with read access to the data categories you want to sync (e.g. People). Calls return 403 until permissions are granted.""",
            iconPath="/static/services/hibob.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hibob",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="service_user_id",
                        label="Service User ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="service_user_token",
                        label="Service User token",
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
        config: HiBobSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # HiBob has no updated-at filters; every stream is full refresh.
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
        self, config: HiBobSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_hibob_credentials(config.service_user_id, config.service_user_token)

    def source_for_pipeline(self, config: HiBobSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return hibob_source(
            service_user_id=config.service_user_id,
            service_user_token=config.service_user_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
