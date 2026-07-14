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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RentCastSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast import (
    RentCastResumeConfig,
    rentcast_source,
    validate_credentials as _validate_rentcast_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.settings import (
    ENDPOINTS,
    RENTCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RentCastSource(ResumableSource[RentCastSourceConfig, RentCastResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RENTCAST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RENT_CAST,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="RentCast",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your RentCast API key to pull US real estate data into the PostHog Data warehouse.

You can create an API key under **API dashboard** in [RentCast](https://app.rentcast.io/app/api). The key grants read access to property records and active sale and rental listings.
""",
            iconPath="/static/services/rentcast.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rentcast",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.rentcast.io": "Your RentCast API key is invalid or has been revoked. Generate a new key in the RentCast API dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.rentcast.io": "Your RentCast API key does not have access to this data. Check the key's plan and permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: RentCastSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — RentCast's list endpoints expose no reliably
        # ordered server-side timestamp filter, so there is no incremental cursor to advance.
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
        self, config: RentCastSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return _validate_rentcast_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RentCastResumeConfig]:
        return ResumableSourceManager[RentCastResumeConfig](inputs, RentCastResumeConfig)

    def source_for_pipeline(
        self,
        config: RentCastSourceConfig,
        resumable_source_manager: ResumableSourceManager[RentCastResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in RENTCAST_ENDPOINTS:
            raise ValueError(f"Unknown RentCast schema '{inputs.schema_name}'")

        return rentcast_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
