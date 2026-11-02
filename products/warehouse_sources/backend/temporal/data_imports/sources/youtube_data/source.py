from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubedata import (
    YoutubeDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.youtube_data import (
    ACCESS_ERROR,
    AUTH_ERROR,
    COMMENTS_ERROR,
    NOT_FOUND_ERROR,
    QUOTA_ERROR,
    REQUEST_ERROR,
    YoutubeDataResumeConfig,
    fetch_channel,
    youtube_data_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YoutubeDataSource(ResumableSource[YoutubeDataSourceConfig, YoutubeDataResumeConfig]):
    codebase_detection = detect(
        env=("^YOUTUBE_(DATA_)?API_KEY$", "^(NEXT_PUBLIC|VITE|REACT_APP)_YOUTUBE_(DATA_)?API_KEY$"),
        npm=("@googleapis/youtube", "simple-youtube-api", "youtube-api"),
        pypi=("python-youtube", "youtube-data-api"),
        cargo=("google-youtube3",),
        composer=("alaouy/youtube", "madcoda/php-youtube-api"),
        maven=("com.google.apis:google-api-services-youtube",),
        pub=("youtube_api",),
        rubygems=("yt", "google-apis-youtube_v3"),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.google.com/youtube/v3/revision_history"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUTUBEDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YOUTUBEDATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="YouTube (Google)",
            caption="Import public data for one YouTube channel. Enable YouTube Data API v3 in your Google Cloud project. "
            "Private data requires OAuth and is not supported. Each sync uses your project's API quota.",
            docsUrl="https://posthog.com/docs/cdp/sources/youtube-data",
            iconPath="/static/services/youtube_data.png",
            keywords=["youtube", "yt"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Google API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="channel_id",
                        label="YouTube channel ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="UC...",
                        caption="Enter the channel ID that starts with UC. Do not enter a handle or URL.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )

    def get_schemas(
        self,
        config: YoutubeDataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, should_sync_default={"comment_threads": False}
        )
        for schema in schemas:
            schema.detected_primary_keys = list(ENDPOINTS[schema.name].primary_keys)
        return schemas

    def validate_credentials(
        self,
        config: YoutubeDataSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unsupported YouTube table: {schema_name}"
        try:
            fetch_channel(config.api_key, config.channel_id, team_id, self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[YoutubeDataResumeConfig]:
        return ResumableSourceManager(inputs, YoutubeDataResumeConfig)

    def source_for_pipeline(
        self,
        config: YoutubeDataSourceConfig,
        resumable_source_manager: ResumableSourceManager[YoutubeDataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return youtube_data_source(
            api_key=config.api_key,
            channel_id=config.channel_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            message: message
            for message in (
                AUTH_ERROR,
                ACCESS_ERROR,
                QUOTA_ERROR,
                REQUEST_ERROR,
                NOT_FOUND_ERROR,
                COMMENTS_ERROR,
                "YouTube channel was not found.",
                "YouTube uploads playlist was not found.",
                "Unsupported YouTube table:",
            )
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS
