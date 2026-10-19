from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout import (
    BuzzsproutDownloadsCursor,
    BuzzsproutResumeConfig,
    buzzsprout_source,
    validate_credentials as validate_buzzsprout_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import (
    BUZZSPROUT_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buzzsprout import (
    BuzzsproutSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuzzsproutSource(
    ResumableSource[BuzzsproutSourceConfig, BuzzsproutResumeConfig],
    CursorSource[BuzzsproutDownloadsCursor],
):
    codebase_detection = detect(env=("^BUZZSPROUT_",))

    api_docs_url = "https://github.com/Buzzsprout/buzzsprout-api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUZZSPROUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BUZZSPROUT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Buzzsprout",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Buzzsprout API token and podcast ID to sync your podcast data into the PostHog Data warehouse.

You can find both your API token and podcast ID in your [Buzzsprout API settings](https://www.buzzsprout.com/my/profile/api).""",
            iconPath="/static/services/buzzsprout.png",
            docsUrl="https://posthog.com/docs/cdp/sources/buzzsprout",
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
                        name="podcast_id",
                        label="Podcast ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when the REST client calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem. Match the stable
            # status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://www.buzzsprout.com": "Your Buzzsprout API token is invalid or has been revoked. Create a new token in your Buzzsprout account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.buzzsprout.com": "Your Buzzsprout API token does not have access to this podcast. Check the token and podcast ID, then reconnect.",
        }

    def get_schemas(
        self,
        config: BuzzsproutSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Buzzsprout's list endpoints return the full array on every request with no server-side
        # timestamp filter, so an "incremental" sync would cost the same as a full refresh. Only
        # `downloads`, which is requested one day at a time, has incremental fields. It re-reads its
        # last days, so append would duplicate rows and it supports merge only.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=[endpoint for endpoint, config in BUZZSPROUT_ENDPOINTS.items() if config.incremental_fields],
            descriptions={
                endpoint: config.description
                for endpoint, config in BUZZSPROUT_ENDPOINTS.items()
                if config.description is not None
            },
            should_sync_default={
                endpoint: config.should_sync_default for endpoint, config in BUZZSPROUT_ENDPOINTS.items()
            },
            default_incremental_lookback_seconds={
                endpoint: config.default_incremental_lookback_seconds
                for endpoint, config in BUZZSPROUT_ENDPOINTS.items()
                if config.default_incremental_lookback_seconds is not None
            },
        )

    def validate_credentials(
        self,
        config: BuzzsproutSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_buzzsprout_credentials(config.api_token, config.podcast_id)

    def cursor_class(self) -> type[BuzzsproutDownloadsCursor]:
        return BuzzsproutDownloadsCursor

    def merge_cursors(
        self, current: BuzzsproutDownloadsCursor, candidate: BuzzsproutDownloadsCursor
    ) -> BuzzsproutDownloadsCursor:
        return max(current, candidate, key=lambda cursor: cursor.next_date)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BuzzsproutResumeConfig]:
        return ResumableSourceManager[BuzzsproutResumeConfig](inputs, BuzzsproutResumeConfig)

    def source_for_pipeline(
        self,
        config: BuzzsproutSourceConfig,
        resumable_source_manager: ResumableSourceManager[BuzzsproutResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return buzzsprout_source(
            api_token=config.api_token,
            podcast_id=config.podcast_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            db_incremental_field_last_value_before_lookback=inputs.db_incremental_field_last_value_before_lookback
            if inputs.should_use_incremental_field
            else None,
            # A full refresh rebuilds the table, so it starts from the first episode and keeps no cursor.
            cursor_manager=self.get_cursor_manager(inputs)
            if BUZZSPROUT_ENDPOINTS[inputs.schema_name].fan_out_over_days and inputs.should_use_incremental_field
            else None,
        )
