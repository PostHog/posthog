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
    InflowinventorySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.inflowinventory import (
    InflowInventoryResumeConfig,
    inflowinventory_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import (
    ENDPOINTS,
    INFLOWINVENTORY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InflowinventorySource(ResumableSource[InflowinventorySourceConfig, InflowInventoryResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFLOWINVENTORY

    @property
    def connection_host_fields(self) -> list[str]:
        # The Bearer key is sent to cloudapi.inflowinventory.com/<company_id>, so retargeting the
        # company ID must re-require the key — otherwise a preserved credential could be aimed at
        # another account's path.
        return ["company_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INFLOWINVENTORY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Inflowinventory",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your inFlow Inventory company ID and API key to pull your inventory and order data into the PostHog Data warehouse.

Find your company ID and create an API key on the **Integrations** page in [inFlow](https://www.inflowinventory.com/). API access requires a paid plan with the API add-on, and the key is only shown once — copy it before leaving the page.
""",
            iconPath="/static/services/inflowinventory.png",
            docsUrl="https://posthog.com/docs/cdp/sources/inflowinventory",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="company_id",
                        label="Company ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://cloudapi.inflowinventory.com": "Your inFlow Inventory API key is invalid or has been revoked. Generate a new key on the Integrations page in inFlow, then reconnect.",
            "403 Client Error: Forbidden for url: https://cloudapi.inflowinventory.com": "Your inFlow Inventory API key does not have access to this data, or the account's plan does not include API access. Check the key and plan, then reconnect.",
        }

    def get_schemas(
        self,
        config: InflowinventorySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — inFlow's list endpoints expose cursor pagination but
        # no reliably ordered server-side timestamp filter, so there is no incremental cursor.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=INFLOWINVENTORY_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InflowinventorySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key, config.company_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InflowInventoryResumeConfig]:
        return ResumableSourceManager[InflowInventoryResumeConfig](inputs, InflowInventoryResumeConfig)

    def source_for_pipeline(
        self,
        config: InflowinventorySourceConfig,
        resumable_source_manager: ResumableSourceManager[InflowInventoryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in INFLOWINVENTORY_ENDPOINTS:
            raise ValueError(f"Unknown inFlow Inventory schema '{inputs.schema_name}'")

        return inflowinventory_source(
            api_key=config.api_key,
            company_id=config.company_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
