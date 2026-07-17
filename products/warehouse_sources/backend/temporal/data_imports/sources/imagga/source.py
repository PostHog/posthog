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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ImaggaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga import (
    imagga_source,
    validate_credentials as validate_imagga_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.settings import IMAGGA_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ImaggaSource(SimpleSource[ImaggaSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IMAGGA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.IMAGGA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Imagga",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Imagga API credentials to pull your account's usage statistics into the PostHog Data warehouse.

Find your API key and secret in the [Imagga dashboard](https://imagga.com/profile/dashboard).

Imagga is an on-demand image-recognition API, so the only account data available to sync is your API consumption (from `GET /usage`): the current billing-period request counters, your monthly limit, and per-day usage.""",
            iconPath="/static/services/imagga.png",
            docsUrl="https://posthog.com/docs/cdp/sources/imagga",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acc_...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Invalid or missing credentials surface as a 401 when `_fetch_usage` calls
            # `raise_for_status()`. Imagga uses 403 when the key is valid but the account can't access
            # the resource. Neither can be fixed by retrying, so stop the sync. Match the stable status
            # text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.imagga.com": "Your Imagga API key or secret is invalid. Copy the correct credentials from your Imagga dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.imagga.com": "Your Imagga account does not have access to this resource. Check your plan and credentials in the Imagga dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: ImaggaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Both endpoints are full refresh only: Imagga's /usage response exposes no server-side
        # timestamp filter, so there is no cursor to sync incrementally.
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )
            for endpoint_config in IMAGGA_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: ImaggaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_imagga_credentials(config.api_key, config.api_secret):
            return True, None

        # The probe also returns False on transient network/timeout errors, so don't claim the
        # credentials are definitively wrong — point at both possibilities.
        return (
            False,
            "Unable to verify your Imagga credentials. Check that the API key and secret are correct and that api.imagga.com is reachable.",
        )

    def source_for_pipeline(self, config: ImaggaSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return imagga_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
