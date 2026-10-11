from typing import Optional, cast

from sources.loops._config import LoopsSourceConfig
from sources.loops.loops import (
    LoopsResumeConfig,
    loops_source,
    validate_credentials as validate_loops_credentials,
)
from sources.loops.settings import ENDPOINTS, INCREMENTAL_FIELDS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
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
class LoopsSource(ResumableSource[LoopsSourceConfig, LoopsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    api_docs_url = "https://loops.so/docs/api-reference/intro"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOOPS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOOPS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Loops",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["loops.so", "email"],
            caption="""Enter your Loops API key to sync your campaigns, transactional emails, mailing lists and other account data into the PostHog Data warehouse.

You can generate an API key in your Loops account under **Settings > API**.

Note: the Loops API has no bulk contact export, so contacts can't be synced. Some tables (campaigns, themes, components) require the Content API to be enabled for your Loops team.""",
            iconPath="/static/services/loops.png",
            docsUrl="https://posthog.com/docs/cdp/sources/loops",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.loops.so": "Your Loops API key is invalid, or this API is not enabled for your Loops team. Check the key in Settings > API and reconnect.",
            "403 Client Error: Forbidden for url: https://app.loops.so": "Your Loops API key does not have permission to access this endpoint.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.loops.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LoopsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: LoopsSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_loops_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LoopsResumeConfig]:
        return ResumableSourceManager[LoopsResumeConfig](inputs, LoopsResumeConfig)

    def source_for_pipeline(
        self,
        config: LoopsSourceConfig,
        resumable_source_manager: ResumableSourceManager[LoopsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return loops_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
