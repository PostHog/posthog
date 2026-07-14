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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MyHoursSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.my_hours import (
    check_access,
    my_hours_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import (
    ENDPOINTS,
    MY_HOURS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MyHoursSource(SimpleSource[MyHoursSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MYHOURS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MY_HOURS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="My Hours",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your My Hours API key to pull your time-tracking data into the PostHog Data warehouse.

API keys are available on paid plans. Create one under **Settings → Integrations → API keys** in your [My Hours account](https://app.myhours.com/). The key is tied to the user who created it, so it stops working if that user is archived or removed. The key grants read access to your clients, projects, tags, and users.
""",
            iconPath="/static/services/my_hours.png",
            docsUrl="https://posthog.com/docs/cdp/sources/my-hours",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api2.myhours.com": "Your My Hours API key is invalid or has been revoked. Generate a new key under Settings → Integrations → API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api2.myhours.com": "Your My Hours API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: MyHoursSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — My Hours list endpoints expose no server-side
        # timestamp filter, so there is no incremental cursor to advance.
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
        self, config: MyHoursSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid My Hours API key"
        return False, message or "Could not validate My Hours API key"

    def source_for_pipeline(self, config: MyHoursSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in MY_HOURS_ENDPOINTS:
            raise ValueError(f"Unknown My Hours schema '{inputs.schema_name}'")

        return my_hours_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
