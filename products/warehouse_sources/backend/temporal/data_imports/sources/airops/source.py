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
from products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops import (
    airops_source,
    validate_credentials as validate_airops_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airops.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AirOpsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AirOpsSource(SimpleSource[AirOpsSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.airops.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIROPS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AIR_OPS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AirOps",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your AirOps workspace API key to sync your AirOps apps and their executions into the PostHog Data warehouse.

You can create a workspace API key in your [AirOps workspace settings](https://app.airops.com). Regenerating the key immediately invalidates the previous one.""",
            iconPath="/static/services/airops.png",
            docsUrl="https://posthog.com/docs/cdp/sources/airops",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.airops.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing, invalid, or regenerated workspace key surfaces as a requests HTTPError once
            # `_fetch_json` calls `raise_for_status()`. No retry can fix a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.airops.com": "Your AirOps API key is invalid or has been regenerated. Create a new workspace API key in your AirOps settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.airops.com": "Your AirOps API key does not have access to this data. Check the key's workspace permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: AirOpsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # AirOps has no server-side timestamp filter and executions mutate after creation, so every
        # table is full refresh only (no incremental / append support).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: AirOpsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_airops_credentials(config.api_key):
            return True, None
        return False, "Invalid AirOps API key"

    def source_for_pipeline(self, config: AirOpsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return airops_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
