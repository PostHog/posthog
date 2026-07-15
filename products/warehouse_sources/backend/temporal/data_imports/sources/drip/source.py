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
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip import (
    DripResumeConfig,
    drip_source,
    validate_credentials as validate_drip_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DripSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DripSource(ResumableSource[DripSourceConfig, DripResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.drip.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRIP

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.drip.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.getdrip.com": "Your Drip API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.getdrip.com": "Your Drip API token does not have access to this account. Please check the token and account ID.",
        }

    def get_schemas(
        self,
        config: DripSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
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
        self, config: DripSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_drip_credentials(config.api_token, config.account_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DripResumeConfig]:
        return ResumableSourceManager[DripResumeConfig](inputs, DripResumeConfig)

    def source_for_pipeline(
        self,
        config: DripSourceConfig,
        resumable_source_manager: ResumableSourceManager[DripResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return drip_source(
            api_token=config.api_token,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DRIP,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Drip",
            caption="""Enter your Drip API token and account ID to pull your Drip data into the PostHog Data warehouse.

You can find your API token under **Settings → User Settings → API** in Drip, and your account ID under **Settings → Account → General Info** (it's the numeric ID in your Drip dashboard URL).""",
            iconPath="/static/services/drip.png",
            docsUrl="https://posthog.com/docs/cdp/sources/drip",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
