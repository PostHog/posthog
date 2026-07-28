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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftclarity import (
    MicrosoftClaritySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.microsoft_clarity import (
    microsoft_clarity_source,
    validate_credentials as validate_clarity_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import (
    APPEND_ONLY_ENDPOINTS,
    DEFAULT_NUM_OF_DAYS,
    DIMENSION_OPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NO_DIMENSION,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _dimension_options() -> list[SourceFieldSelectConfigOption]:
    return [
        SourceFieldSelectConfigOption(label="None", value=NO_DIMENSION),
        *(SourceFieldSelectConfigOption(label=dimension, value=dimension) for dimension in DIMENSION_OPTIONS),
    ]


@SourceRegistry.register
class MicrosoftClaritySource(SimpleSource[MicrosoftClaritySourceConfig]):
    lists_tables_without_credentials = True  # static, single endpoint — safe for public docs
    api_docs_url = "https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTCLARITY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Microsoft Clarity API token is invalid or expired. Generate a new token in Clarity under Settings -> Data Export and reconnect.",
            "403 Client Error": "This Microsoft Clarity API token is not authorized for this project.",
            "429 Client Error": "The Microsoft Clarity daily quota (10 requests per project) has been used up. Try again after the quota resets.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MicrosoftClaritySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, append_only=APPEND_ONLY_ENDPOINTS)

    def validate_credentials(
        self,
        config: MicrosoftClaritySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_clarity_credentials(config.api_token)

    def source_for_pipeline(self, config: MicrosoftClaritySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return microsoft_clarity_source(
            token=config.api_token,
            num_of_days=config.num_of_days,
            dimension1=config.dimension1,
            dimension2=config.dimension2,
            dimension3=config.dimension3,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_CLARITY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Microsoft Clarity",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Generate an API token in your Clarity project under **Settings -> Data Export -> Generate new API token**, then paste it below.

Microsoft Clarity's export API allows a maximum of 10 requests per project per day and only returns the last 1-3 days of data (no historical backfill), so PostHog syncs a rolling snapshot on each run rather than pulling full history.""",
            docsUrl="https://posthog.com/docs/cdp/sources/microsoft-clarity",
            iconPath="/static/services/microsoft_clarity.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="num_of_days",
                        label="Reporting window",
                        required=True,
                        defaultValue=DEFAULT_NUM_OF_DAYS,
                        options=[
                            SourceFieldSelectConfigOption(label="Last 24 hours", value="1"),
                            SourceFieldSelectConfigOption(label="Last 48 hours", value="2"),
                            SourceFieldSelectConfigOption(label="Last 72 hours", value="3"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="dimension1",
                        label="Breakdown dimension 1 (optional)",
                        required=False,
                        defaultValue=NO_DIMENSION,
                        options=_dimension_options(),
                    ),
                    SourceFieldSelectConfig(
                        name="dimension2",
                        label="Breakdown dimension 2 (optional)",
                        required=False,
                        defaultValue=NO_DIMENSION,
                        options=_dimension_options(),
                    ),
                    SourceFieldSelectConfig(
                        name="dimension3",
                        label="Breakdown dimension 3 (optional)",
                        required=False,
                        defaultValue=NO_DIMENSION,
                        options=_dimension_options(),
                    ),
                ],
            ),
        )
