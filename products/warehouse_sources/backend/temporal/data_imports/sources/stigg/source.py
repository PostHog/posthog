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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StiggSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.settings import ENDPOINTS, STIGG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.stigg import (
    StiggResumeConfig,
    stigg_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StiggSource(ResumableSource[StiggSourceConfig, StiggResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STIGG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STIGG,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Stigg",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Stigg server API key to pull your pricing, packaging, and monetization data into the PostHog Data warehouse.

You can find your server API key under **Settings → Integrations → API keys** in [Stigg](https://app.stigg.io). The key grants read access to your customers, subscriptions, products, plans, addons, features, and coupons.
""",
            iconPath="/static/services/stigg.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stigg",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Server API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.stigg.io": "Your Stigg API key is invalid or has been revoked. Generate a new server API key under Settings → Integrations → API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.stigg.io": "Your Stigg API key does not have access to this data. Use a server API key with read access, then reconnect.",
        }

    def get_schemas(
        self,
        config: StiggSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only. Stigg's list endpoints filter by `createdAt` but
        # expose no updated-since filter, and billing objects mutate in place, so there is no
        # incremental cursor that would also capture updates.
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
        self, config: StiggSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Server API keys are environment-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StiggResumeConfig]:
        return ResumableSourceManager[StiggResumeConfig](inputs, StiggResumeConfig)

    def source_for_pipeline(
        self,
        config: StiggSourceConfig,
        resumable_source_manager: ResumableSourceManager[StiggResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in STIGG_ENDPOINTS:
            raise ValueError(f"Unknown Stigg schema '{inputs.schema_name}'")

        return stigg_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
