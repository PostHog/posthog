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
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.aviator import (
    AviatorResumeConfig,
    aviator_source,
    validate_credentials as validate_aviator_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.settings import (
    AVIATOR_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AviatorSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AviatorSource(ResumableSource[AviatorSourceConfig, AviatorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AVIATOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AVIATOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Aviator",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Aviator API token to pull your merge-queue data into the PostHog Data warehouse.

Create a user access token (it starts with `av_uat_`) from your [Aviator account settings](https://www.aviator.co/), then paste it below. The token inherits your account's repository access, so no extra scopes are required.""",
            iconPath="/static/services/aviator.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/aviator",
            keywords=["merge queue", "pull requests", "ci", "developer productivity"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="av_uat_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.aviator.co": "Your Aviator API token is invalid or has been revoked. Create a new user access token in your Aviator account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.aviator.co": "Your Aviator API token is missing access to this data. Check the token's repository access in your Aviator account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: AviatorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = AVIATOR_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Analytics rows are daily aggregates that get revised; incremental re-pulls a window
                # that merge dedupes, so append (which would duplicate them) is never offered.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AviatorSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_aviator_credentials(config.api_token):
            return True, None

        return False, "Invalid Aviator API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AviatorResumeConfig]:
        return ResumableSourceManager[AviatorResumeConfig](inputs, AviatorResumeConfig)

    def source_for_pipeline(
        self,
        config: AviatorSourceConfig,
        resumable_source_manager: ResumableSourceManager[AviatorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aviator_source(
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
