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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PrintifySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.printify import (
    PrintifyResumeConfig,
    printify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.settings import (
    ENDPOINTS,
    PRINTIFY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PrintifySource(ResumableSource[PrintifySourceConfig, PrintifyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRINTIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PRINTIFY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Printify",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Printify personal access token to pull your print-on-demand data into the PostHog Data warehouse.

You can generate a token under **My Profile → Connections** in [Printify](https://printify.com). The token needs the `shops.read`, `products.read`, `orders.read`, `uploads.read`, `webhooks.read`, and `catalog.read` scopes. Personal access tokens expire after one year.
""",
            iconPath="/static/services/printify.png",
            docsUrl="https://posthog.com/docs/cdp/sources/printify",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.printify.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.printify.com": "Your Printify API token is invalid or has expired. Generate a new token under My Profile → Connections, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.printify.com": "Your Printify API token does not have access to this data. Check the token's scopes, then reconnect.",
        }

    def get_schemas(
        self,
        config: PrintifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Printify's list endpoints expose no server-side
        # `updated_at`/`since` filter, so there is no incremental cursor to advance.
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
        self, config: PrintifySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # One probe against the shop list validates the token; the shop list is also a hard
        # prerequisite for every shop-scoped stream, so this is the scope that matters most.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PrintifyResumeConfig]:
        return ResumableSourceManager[PrintifyResumeConfig](inputs, PrintifyResumeConfig)

    def source_for_pipeline(
        self,
        config: PrintifySourceConfig,
        resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PRINTIFY_ENDPOINTS:
            raise ValueError(f"Unknown Printify schema '{inputs.schema_name}'")

        return printify_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
