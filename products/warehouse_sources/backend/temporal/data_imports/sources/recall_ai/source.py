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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recallai import (
    RecallAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.recall_ai import (
    REGIONS,
    RecallAIResumeConfig,
    recall_ai_source,
    validate_credentials as validate_recall_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RecallAISource(ResumableSource[RecallAISourceConfig, RecallAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # Recall.ai versions per resource (/api/v1/ for bots and artifacts, /api/v2/ for
    # calendars) with no workspace-wide version to pin, so the framework's unversioned
    # default applies.
    api_docs_url = "https://docs.recall.ai/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RECALLAI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Recall.ai API key is invalid, or it belongs to a different region. Check the key and the region, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Recall.ai API key doesn't have access to this data. Check the key in your Recall.ai dashboard.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RecallAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: RecallAISourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.region not in REGIONS:
            return (
                False,
                f"Choose one of the supported Recall.ai regions: {', '.join(REGIONS)}.",
            )

        is_valid, _status = validate_recall_ai_credentials(config.api_key, config.region)
        if is_valid:
            return True, None

        return (
            False,
            "Couldn't connect to Recall.ai. Check that your API key is valid and that you selected the region it was created in.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RecallAIResumeConfig]:
        return ResumableSourceManager[RecallAIResumeConfig](inputs, RecallAIResumeConfig)

    def source_for_pipeline(
        self,
        config: RecallAISourceConfig,
        resumable_source_manager: ResumableSourceManager[RecallAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return recall_ai_source(
            api_key=config.api_key,
            region=config.region,
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
            name=ExternalDataSourceType.RECALLAI,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Recall.ai",
            caption="Sync meeting bots, recordings, transcripts, participant events, and calendar data from Recall.ai.",
            docsUrl="https://posthog.com/docs/cdp/sources/recall-ai",
            iconPath="/static/services/recall_ai.png",
            keywords=["meetings", "call recording", "transcripts", "bots"],
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
                        caption="Create an API key in your Recall.ai dashboard under API keys.",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us-east-1",
                        caption="API keys only work in the region they were created in. Find yours in your Recall.ai dashboard URL.",
                        options=[
                            SourceFieldSelectConfigOption(label="US East (us-east-1)", value="us-east-1"),
                            SourceFieldSelectConfigOption(label="US West (us-west-2)", value="us-west-2"),
                            SourceFieldSelectConfigOption(label="EU (eu-central-1)", value="eu-central-1"),
                            SourceFieldSelectConfigOption(label="Japan (ap-northeast-1)", value="ap-northeast-1"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
