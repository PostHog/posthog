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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SegmentSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment import (
    SegmentResumeConfig,
    segment_source,
    validate_credentials as validate_segment_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import (
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SEGMENT_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SegmentSource(ResumableSource[SegmentSourceConfig, SegmentResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEGMENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SEGMENT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Segment",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter a Twilio Segment workspace-scoped Public API token to pull your Segment workspace configuration into the PostHog Data warehouse.

Create a **Public API token** in your Segment workspace under **Settings → Access Management → Tokens**, and pick the region your workspace lives in.

This connects to the Segment **Public API** (workspace configuration, admin, and metadata) — not the event or Profile data plane.""",
            iconPath="/static/services/segment.png",
            docsUrl="https://posthog.com/docs/cdp/sources/segment",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.segmentapis.com)", value="api"),
                            SourceFieldSelectConfigOption(label="EU (eu1.api.segmentapis.com)", value="eu1"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Public API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or insufficiently-scoped Public API token surfaces as a requests
            # HTTPError when `_fetch` calls `raise_for_status()`. Retrying can never fix a credential
            # problem, so stop the sync. Segment returns 401 when the header is missing and 403 for a
            # token that's present but not authorized; match the stable status text only.
            "401 Client Error: Unauthorized for url": "Your Segment Public API token is missing or invalid. Create a new Public API token in your Segment workspace settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Segment Public API token is invalid, revoked, or missing the permissions needed to sync this data. Create a new token with the required access in your Segment workspace settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SegmentSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The Segment Public API exposes no server-side timestamp filter on these resources, so every
        # endpoint is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=SEGMENT_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SegmentSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_segment_credentials(config.api_token, config.region):
            return True, None

        return False, "Invalid Segment Public API token, or wrong region selected for this token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SegmentResumeConfig]:
        return ResumableSourceManager[SegmentResumeConfig](inputs, SegmentResumeConfig)

    def source_for_pipeline(
        self,
        config: SegmentSourceConfig,
        resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return segment_source(
            api_token=config.api_token,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
