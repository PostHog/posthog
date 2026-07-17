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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JellyfishSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.jellyfish import (
    JellyfishResumeConfig,
    jellyfish_source,
    validate_credentials as validate_jellyfish_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JellyfishSource(ResumableSource[JellyfishSourceConfig, JellyfishResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JELLYFISH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JELLYFISH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Jellyfish",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Jellyfish API token to pull your engineering-intelligence data (R&D allocations, delivery deliverables, engineering metrics, engineers, and teams) into the PostHog Data warehouse.

Generate a token in Jellyfish under **Settings → Data Connections → API Export** (requires the API Export feature on your plan and an Admin user role). Note that Jellyfish tokens are created with an expiry — reconnect with a fresh token when yours expires.""",
            iconPath="/static/services/jellyfish.png",
            docsUrl="https://posthog.com/docs/cdp/sources/jellyfish",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Jellyfish returns 403 for both missing and invalid/expired tokens (verified live); 401 is
        # covered in case that ever changes. Retrying can never satisfy a credential problem.
        return {
            "401 Client Error: Unauthorized for url: https://app.jellyfish.co": "Your Jellyfish API token is invalid or has expired. Generate a new token under Settings → Data Connections → API Export in Jellyfish, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.jellyfish.co": "Your Jellyfish API token is invalid or has expired. Generate a new token under Settings → Data Connections → API Export in Jellyfish, then reconnect.",
        }

    def get_schemas(
        self,
        config: JellyfishSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full-refresh: the export API filters by date window rather than an
        # updated-since cursor, and windowed aggregates can be restated, so each sync rebuilds the
        # (small) tables from the whole lookback range.
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
        self, config: JellyfishSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_jellyfish_credentials(config.api_token):
            return True, None

        return False, "Invalid Jellyfish API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JellyfishResumeConfig]:
        return ResumableSourceManager[JellyfishResumeConfig](inputs, JellyfishResumeConfig)

    def source_for_pipeline(
        self,
        config: JellyfishSourceConfig,
        resumable_source_manager: ResumableSourceManager[JellyfishResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return jellyfish_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
