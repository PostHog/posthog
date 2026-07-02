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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmartsheetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet import (
    SmartsheetResumeConfig,
    smartsheet_source,
    validate_credentials as validate_smartsheet_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartsheetSource(ResumableSource[SmartsheetSourceConfig, SmartsheetResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTSHEET

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.smartsheet.com": "Smartsheet authentication failed. Your access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.smartsheet.com": "Smartsheet denied access. Please check that your access token has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SMARTSHEET,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Smartsheet",
            caption="""Enter your Smartsheet API access token to pull your Smartsheet data into the PostHog Data warehouse.

You can generate a personal access token under **Personal Settings → API Access** in your [Smartsheet account](https://app.smartsheet.com). The token inherits your account's read access; the `users` table additionally requires a system administrator account.""",
            iconPath="/static/services/smartsheet.png",
            docsUrl="https://posthog.com/docs/cdp/sources/smartsheet",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: SmartsheetSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SmartsheetSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_smartsheet_credentials(config.access_token):
            return True, None

        return False, "Invalid Smartsheet access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmartsheetResumeConfig]:
        return ResumableSourceManager[SmartsheetResumeConfig](inputs, SmartsheetResumeConfig)

    def source_for_pipeline(
        self,
        config: SmartsheetSourceConfig,
        resumable_source_manager: ResumableSourceManager[SmartsheetResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return smartsheet_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
