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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RssSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.rss import (
    RssResumeConfig,
    rss_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.settings import ENDPOINTS, RSS_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RssSource(ResumableSource[RssSourceConfig, RssResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RSS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RSS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="RSS.com",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["podcast", "podcasting"],
            caption="""Enter your RSS.com API key to pull your podcast and episode data into the PostHog Data warehouse.

The RSS.com API is available on Network plans. You can create an API key under **Profile → API Access** in [RSS.com](https://rss.com).
""",
            iconPath="/static/services/rss.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rss",
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
            # Hidden until the source has been validated against a live RSS.com Network-plan
            # account — the API launched in public beta in early 2026 and behavior was verified
            # against its OpenAPI spec only.
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rss.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.rss.com": "Your RSS.com API key is invalid or has been revoked. Generate a new key under Profile → API Access, then reconnect.",
            "402 Client Error: Payment Required for url: https://api.rss.com": "The RSS.com API is only available on RSS.com Network plans. Upgrade your plan, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.rss.com": "Your RSS.com API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: RssSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the RSS.com API exposes no server-side timestamp
        # filter on any list endpoint, so there is no incremental cursor to advance.
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
        self, config: RssSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RssResumeConfig]:
        return ResumableSourceManager[RssResumeConfig](inputs, RssResumeConfig)

    def source_for_pipeline(
        self,
        config: RssSourceConfig,
        resumable_source_manager: ResumableSourceManager[RssResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in RSS_ENDPOINTS:
            raise ValueError(f"Unknown RSS.com schema '{inputs.schema_name}'")

        return rss_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
