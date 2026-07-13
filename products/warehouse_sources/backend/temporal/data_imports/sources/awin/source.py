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
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.awin import (
    AwinResumeConfig,
    awin_source,
    validate_credentials as validate_awin_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.settings import (
    AWIN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AwinSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwinSource(ResumableSource[AwinSourceConfig, AwinResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWIN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWIN,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Awin",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Awin API token to pull your Awin affiliate data into the PostHog Data warehouse.

Create a personal OAuth2 token from the [Awin API settings](https://ui.awin.com/awin-api). The same token grants access to every publisher account your user can see.""",
            iconPath="/static/services/awin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/awin",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.awin.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.awin.com": "Your Awin API token is invalid or has expired. Create a new token in your Awin API settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.awin.com": "Your Awin API token does not have access to this data. Check the token's account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: AwinSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "reports_advertiser":
                return "Full refresh only. A rolling snapshot of the last 30 days of performance, aggregated per advertiser"
            if endpoint == "transactions":
                return "Only syncs the last 365 days on initial sync"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=AWIN_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AwinSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_awin_credentials(config.api_token):
            return True, None

        return False, "Invalid Awin API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwinResumeConfig]:
        return ResumableSourceManager[AwinResumeConfig](inputs, AwinResumeConfig)

    def source_for_pipeline(
        self,
        config: AwinSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwinResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return awin_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
