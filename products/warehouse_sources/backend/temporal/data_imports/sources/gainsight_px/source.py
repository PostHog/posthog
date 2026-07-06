from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px import (
    GainsightPxResumeConfig,
    gainsight_px_source,
    validate_credentials as validate_gainsight_px_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    ENDPOINTS,
    GAINSIGHT_PX_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GainsightPxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GainsightPxSource(ResumableSource[GainsightPxSourceConfig, GainsightPxResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GAINSIGHTPX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Gainsight PX rejected the API key. Generate a new key with Read access under "
            "Administration → REST API in Gainsight PX, then reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "403 Client Error: Forbidden": message,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GainsightPxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every Gainsight PX list endpoint is full refresh — none exposes a server-side "updated
        # since" filter, so there's no reliable incremental cursor.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=GAINSIGHT_PX_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GainsightPxSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        if validate_gainsight_px_credentials(config.api_key, config.region):
            return True, None

        return False, "Invalid Gainsight PX API key or region. Check the key and the region you selected."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GainsightPxResumeConfig]:
        return ResumableSourceManager[GainsightPxResumeConfig](inputs, GainsightPxResumeConfig)

    def source_for_pipeline(
        self,
        config: GainsightPxSourceConfig,
        resumable_source_manager: ResumableSourceManager[GainsightPxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gainsight_px_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GAINSIGHT_PX,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Gainsight PX",
            caption=(
                "Connect Gainsight PX with your project's **API key**. Generate a key with **Read** "
                "access under **Administration → REST API** in Gainsight PX, then pick the region your "
                "subscription is hosted in.\n\n"
                "All tables are synced as full refresh — Gainsight PX's list endpoints don't expose an "
                '"updated since" filter.'
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/gainsight-px",
            iconPath="/static/services/gainsight_px.png",
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
                ],
            ),
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )
