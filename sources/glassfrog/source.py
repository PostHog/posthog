from typing import Optional, cast

from sources.glassfrog._config import GlassfrogSourceConfig
from sources.glassfrog.glassfrog import (
    glassfrog_source,
    validate_credentials as validate_glassfrog_credentials,
)
from sources.glassfrog.settings import ENDPOINTS, INCREMENTAL_FIELDS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    SimpleSource,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class GlassfrogSource(SimpleSource[GlassfrogSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://app.glassfrog.com/api/v3/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GLASSFROG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GLASSFROG,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="GlassFrog",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your GlassFrog API key to sync your organization's circles, roles, people, projects, actions, tensions, proposals, governance meetings, metrics, and checklist items into the PostHog Data warehouse.

You can create a v3 API key in GlassFrog under [Profile & Settings > API](https://app.glassfrog.com/). The key grants access at your user's permission level.""",
            iconPath="/static/services/glassfrog.png",
            docsUrl="https://posthog.com/docs/cdp/sources/glassfrog",
            keywords=["holacracy", "governance"],
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.glassfrog.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as an HTTPError from `raise_for_status()`. Retrying
            # can never satisfy a credential problem, so stop the sync. Match the stable status text
            # and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.glassfrog.com": "Your GlassFrog API key is invalid or has been revoked. Create a new key under Profile & Settings > API in GlassFrog, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.glassfrog.com": "Your GlassFrog API key does not have access to this data. Check the key's permission level, then reconnect.",
        }

    def get_schemas(
        self,
        config: GlassfrogSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every GlassFrog endpoint is full refresh: the v3 API exposes no server-side timestamp or
        # cursor filters, so nothing can be synced incrementally (see settings.py).
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GlassfrogSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_glassfrog_credentials(config.api_key):
            return True, None

        return False, "Invalid GlassFrog API key"

    def source_for_pipeline(self, config: GlassfrogSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return glassfrog_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
