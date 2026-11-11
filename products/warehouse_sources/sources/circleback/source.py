from typing import Optional, cast

from products.warehouse_sources.sources.circleback._config import CirclebackSourceConfig
from products.warehouse_sources.sources.circleback.circleback import (
    CirclebackResumeConfig,
    circleback_source,
    validate_credentials as validate_circleback_credentials,
)
from products.warehouse_sources.sources.circleback.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "Circleback"


@SourceRegistry.register
class CirclebackSource(ResumableSource[CirclebackSourceConfig, CirclebackResumeConfig]):
    codebase_detection = detect(env=("^CIRCLEBACK_",))

    api_docs_url = "https://circleback.ai/docs/api"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Circleback",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Circleback API key to pull your meetings, transcripts and action items into the PostHog Data warehouse.

Create a key in Circleback under **Settings > API keys**. The key starts with `cb_`.

The sync includes every meeting the key's owner can access, including meetings shared with them. Private notes are not synced.

The transcripts table makes one request per meeting. On the Circleback Free plan, the rate limit of 20 requests a minute makes this table slow to sync.
""",
            iconPath="/static/warehouse-sources/circleback/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/circleback",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="cb_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.circleback.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CirclebackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CirclebackSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_circleback_credentials(config.api_key)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Circleback didn't accept your API key. Create a new key in Circleback under Settings > API keys, then reconnect the source.",
            "403 Client Error: Forbidden": "Circleback refused access with your API key. Create a new key in Circleback under Settings > API keys, then reconnect the source.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CirclebackResumeConfig]:
        return ResumableSourceManager[CirclebackResumeConfig](inputs, CirclebackResumeConfig)

    def source_for_pipeline(
        self,
        config: CirclebackSourceConfig,
        resumable_source_manager: ResumableSourceManager[CirclebackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return circleback_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
