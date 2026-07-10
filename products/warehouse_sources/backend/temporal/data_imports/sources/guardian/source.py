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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GuardianSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.guardian import (
    GuardianResumeConfig,
    guardian_source,
    validate_credentials as validate_guardian_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.settings import (
    ENDPOINTS,
    GUARDIAN_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GuardianSource(ResumableSource[GuardianSourceConfig, GuardianResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GUARDIAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GUARDIAN,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="The Guardian",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Guardian Open Platform API key to pull Guardian news content into the PostHog Data warehouse.

You can request a free developer key from the [Guardian Open Platform](https://open-platform.theguardian.com/access/). Free keys are rate-limited (~12 requests/second, ~5,000 requests/day), so an initial backfill of the full content archive can take a while.
""",
            iconPath="/static/services/guardian.png",
            docsUrl="https://posthog.com/docs/cdp/sources/guardian",
            keywords=["news", "guardian", "content", "media", "articles"],
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://content.guardianapis.com": "Your Guardian API key is invalid or has been revoked. Request a new key from the Guardian Open Platform, then reconnect.",
            "403 Client Error: Forbidden for url: https://content.guardianapis.com": "Your Guardian API key does not have access to this endpoint. Check your key's tier on the Guardian Open Platform, then reconnect.",
        }

    def get_schemas(
        self,
        config: GuardianSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = GUARDIAN_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GuardianSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_guardian_credentials(config.api_key):
            return True, None

        return False, "Invalid Guardian API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GuardianResumeConfig]:
        return ResumableSourceManager[GuardianResumeConfig](inputs, GuardianResumeConfig)

    def source_for_pipeline(
        self,
        config: GuardianSourceConfig,
        resumable_source_manager: ResumableSourceManager[GuardianResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return guardian_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
