from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twitter import (
    TwitterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter.settings import (
    API_VERSION_2,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter.twitter import (
    TwitterResumeConfig,
    endpoint_permissions,
    twitter_source,
    validate_credentials as validate_twitter_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwitterSource(ResumableSource[TwitterSourceConfig, TwitterResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = (API_VERSION_2,)
    default_version = API_VERSION_2
    api_docs_url = "https://docs.x.com/x-api/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWITTER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.x.com": "X rejected the bearer token. Generate a new one in the X developer portal and reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.x.com": "Your X app cannot read this endpoint. Check the project's API access and credit balance in the X developer portal, or stop syncing this table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.twitter.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TwitterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TwitterSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_twitter_credentials(config.bearer_token, config.username)

    def get_endpoint_permissions(
        self, config: TwitterSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return endpoint_permissions(config.bearer_token, config.username, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TwitterResumeConfig]:
        return ResumableSourceManager[TwitterResumeConfig](inputs, TwitterResumeConfig)

    def source_for_pipeline(
        self,
        config: TwitterSourceConfig,
        resumable_source_manager: ResumableSourceManager[TwitterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return twitter_source(
            bearer_token=config.bearer_token,
            username=config.username,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TWITTER,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Twitter",
            keywords=["x", "x.com"],
            caption=(
                "Sync one X account's profile, posts, mentions and audience. "
                "**X charges your own developer project for every post this source reads.** "
                "Create an app in the [X developer portal](https://developer.x.com/en/portal/dashboard), "
                "attach it to a project that has API credits, then copy the app's **Bearer Token**."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/twitter",
            iconPath="/static/services/twitter.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="bearer_token",
                        label="Bearer token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Account handle",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="posthog",
                        secret=False,
                    ),
                ],
            ),
        )
