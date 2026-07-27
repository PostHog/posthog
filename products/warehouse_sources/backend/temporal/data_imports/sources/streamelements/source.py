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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.streamelements import (
    StreamElementsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.streamelements import (
    StreamElementsResumeConfig,
    streamelements_source,
    validate_credentials as validate_streamelements_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StreamElementsSource(ResumableSource[StreamElementsSourceConfig, StreamElementsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://dev.streamelements.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STREAMELEMENTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STREAM_ELEMENTS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["twitch", "streaming", "tips", "donations"],
            label="StreamElements",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync tips, activity feed events, loyalty points, store redemptions and chatbot settings from StreamElements into the PostHog Data warehouse.

Use the channel JWT token from your StreamElements dashboard: open your account page, enable **Show secrets** under **Channels**, then copy the JWT token. An OAuth2 access token also works if it has the `channel:read`, `tips:read`, `activities:read`, `loyalty:read` and `store:read` scopes.
""",
            iconPath="/static/services/streamelements.png",
            docsUrl="https://posthog.com/docs/cdp/sources/streamelements",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="JWT token",
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
            "401 Client Error: Unauthorized for url: https://api.streamelements.com": "Your StreamElements token is invalid or expired. Copy a fresh JWT token from the StreamElements dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.streamelements.com": "Your StreamElements token does not have access to this resource. Check the token scopes and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StreamElementsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Merge only: resume re-fetches the last checkpointed page and the activities window
        # walk overlaps page boundaries by design, so append mode would duplicate rows.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: StreamElementsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_streamelements_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StreamElementsResumeConfig]:
        return ResumableSourceManager[StreamElementsResumeConfig](inputs, StreamElementsResumeConfig)

    def source_for_pipeline(
        self,
        config: StreamElementsSourceConfig,
        resumable_source_manager: ResumableSourceManager[StreamElementsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return streamelements_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
