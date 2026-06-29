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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px import (
    gainsight_px_source,
    validate_credentials as validate_gainsight_px_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    ENDPOINTS,
    GAINSIGHT_PX_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GainsightPxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GainsightPxSource(SimpleSource[GainsightPxSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GAINSIGHTPX

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` selects which Gainsight PX host the stored API key is sent to; retargeting it must
        # re-require the key so it can't be aimed at an attacker-controlled host.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GAINSIGHT_PX,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Gainsight PX",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your Gainsight PX instance to pull accounts, users, segments, features and Knowledge Center content into the PostHog Data warehouse.

Create an API key in Gainsight PX under **Administration → REST API → New API Key**, grant it **READ** permission, and copy the key (it's shown only once).

Pick the **region** that matches your PX instance — it follows your PX app URL: `app.aptrinsic.com` → US, `app-eu.aptrinsic.com` → EU, `app-us2.aptrinsic.com` → US2.""",
            iconPath="/static/services/gainsight_px.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gainsight-px",
            keywords=["gainsight", "aptrinsic", "px"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.aptrinsic.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api-eu.aptrinsic.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="US2 (api-us2.aptrinsic.com)", value="us2"),
                        ],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/revoked key surfaces as an HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Match the stable status text (the host varies by region), not the per-request URL.
            "401 Client Error: Unauthorized": "Gainsight PX rejected the API key. Create a new key under Administration → REST API in Gainsight PX, grant it READ access, then reconnect.",
            "403 Client Error: Forbidden": "The Gainsight PX API key is missing READ access for this resource. Grant READ permission to the key under Administration → REST API, then reconnect.",
        }

    def get_schemas(
        self,
        config: GainsightPxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every PX entity endpoint is full-refresh: there's no server-side modified-since filter to
        # drive an incremental cursor, so we don't advertise one (matching the Airbyte connector).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=GAINSIGHT_PX_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GainsightPxSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_gainsight_px_credentials(region=config.region, api_key=config.api_key):
            return True, None
        return (
            False,
            "Could not authenticate with Gainsight PX. Check the API key and that the selected region matches your PX instance.",
        )

    def source_for_pipeline(self, config: GainsightPxSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return gainsight_px_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
