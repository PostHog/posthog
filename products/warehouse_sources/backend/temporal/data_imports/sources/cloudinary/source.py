from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.cloudinary import (
    CloudinaryResumeConfig,
    cloudinary_source,
    validate_credentials as validate_cloudinary_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudinary import (
    CloudinarySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudinarySource(ResumableSource[CloudinarySourceConfig, CloudinaryResumeConfig]):
    supported_versions = ("v1_1",)
    default_version = "v1_1"
    api_docs_url = "https://cloudinary.com/documentation/admin_api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDINARY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api": "Cloudinary rejected these credentials. Check the API key and secret in your Cloudinary console and reconnect the source.",
            "403 Client Error: Forbidden for url: https://api": "These Cloudinary credentials cannot read this data. Check the key's permissions and reconnect the source.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOUDINARY,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Cloudinary",
            caption="""Enter your Cloudinary cloud name, API key, and API secret to sync your media library metadata into the PostHog Data warehouse: images, videos, raw files, folders, transformations, and upload presets.

Find all three in your Cloudinary console under Settings, then API Keys. The source only reads metadata, so a key with read access is enough. Media files themselves are never downloaded.

Cloudinary limits Admin API calls per hour, 500 on free plans, so a first sync of a large media library can take a while.""",
            iconPath="/static/services/cloudinary.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudinary",
            keywords=["cloudinary.com", "media", "images", "cdn"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="cloud_name",
                        label="Cloud name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-cloud",
                        secret=False,
                        caption="Shown at the top of your Cloudinary console.",
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="global",
                        options=[
                            SourceFieldSelectConfigOption(label="Global (api.cloudinary.com)", value="global"),
                            SourceFieldSelectConfigOption(label="Europe (api-eu.cloudinary.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="Asia Pacific (api-ap.cloudinary.com)", value="ap"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloudinarySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CloudinarySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_cloudinary_credentials(config.cloud_name, config.api_key, config.api_secret, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloudinaryResumeConfig]:
        return ResumableSourceManager[CloudinaryResumeConfig](inputs, CloudinaryResumeConfig)

    def source_for_pipeline(
        self,
        config: CloudinarySourceConfig,
        resumable_source_manager: ResumableSourceManager[CloudinaryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Cloudinary endpoint: {inputs.schema_name}")

        return cloudinary_source(
            cloud_name=config.cloud_name,
            api_key=config.api_key,
            api_secret=config.api_secret,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
