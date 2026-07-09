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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MentionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.mention import (
    MentionResumeConfig,
    mention_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.settings import (
    ENDPOINTS,
    MENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MentionSource(ResumableSource[MentionSourceConfig, MentionResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MENTION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MENTION,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Mention",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["social listening", "media monitoring", "brand monitoring"],
            caption="""Enter your Mention API access token to pull your monitored accounts, alerts, mentions, and tags into the PostHog Data warehouse.

You can create an access token by registering an API application at [dev.mention.com](https://dev.mention.com). Note that Mention API access is a paid add-on to Mention plans.
""",
            iconPath="/static/services/mention.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mention",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mention.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mention.net": "Your Mention access token is invalid or has expired. Generate a new token from your API application at dev.mention.com, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.mention.net": "Your Mention access token does not have access to this data. Check that API access is enabled on your Mention plan, then reconnect.",
        }

    def get_schemas(
        self,
        config: MentionSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — mentions expose a `since_id` cursor, but it orders
        # by fetch recency rather than a timestamp, and it could not be verified against a live
        # account, so there is no trustworthy server-side cursor to advance an incremental sync.
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
        self, config: MentionSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The access token is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MentionResumeConfig]:
        return ResumableSourceManager[MentionResumeConfig](inputs, MentionResumeConfig)

    def source_for_pipeline(
        self,
        config: MentionSourceConfig,
        resumable_source_manager: ResumableSourceManager[MentionResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in MENTION_ENDPOINTS:
            raise ValueError(f"Unknown Mention schema '{inputs.schema_name}'")

        return mention_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
