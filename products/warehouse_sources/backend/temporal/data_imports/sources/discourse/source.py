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
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.discourse import (
    DiscourseResumeConfig,
    discourse_source,
    validate_credentials as validate_discourse_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.discourse import (
    DiscourseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DiscourseSource(ResumableSource[DiscourseSourceConfig, DiscourseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    api_docs_url = "https://docs.discourse.org"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DISCOURSE

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent, and `api_username` selects the identity an
        # All Users key acts as — retargeting either while the key is preserved must re-require the key.
        return ["base_url", "api_username"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DISCOURSE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Discourse",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["forum", "community"],
            caption="""Connect your Discourse community forum to sync categories, topics, posts, tags, groups, and user stats into the PostHog Data warehouse.

Generate an Admin API key under **Admin > API > Keys** on your Discourse instance (a key scoped to "Global" access, or scoped to read the tables below, both work). The instance URL is your forum's address, e.g. `https://yourforum.discourse.group`.""",
            iconPath="/static/services/discourse.png",
            docsUrl="https://posthog.com/docs/cdp/sources/discourse",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://yourforum.discourse.group",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_username",
                        label="API username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="system",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error": "Your Discourse API key or username is invalid, or does not have permission to access this resource. Please check the key and username and reconnect.",
            "invalid_access": "Your Discourse API key or username is invalid, or does not have permission to access this resource. Please check the key and username and reconnect.",
        }

    def get_schemas(
        self,
        config: DiscourseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DiscourseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_discourse_credentials(
            config.base_url, config.api_key, config.api_username, schema_name, team_id
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DiscourseResumeConfig]:
        return ResumableSourceManager[DiscourseResumeConfig](inputs, DiscourseResumeConfig)

    def source_for_pipeline(
        self,
        config: DiscourseSourceConfig,
        resumable_source_manager: ResumableSourceManager[DiscourseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Discourse schema '{inputs.schema_name}'")

        return discourse_source(
            base_url=config.base_url,
            api_key=config.api_key,
            api_username=config.api_username,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
