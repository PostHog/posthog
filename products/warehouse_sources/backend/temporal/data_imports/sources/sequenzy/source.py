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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sequenzy import (
    SequenzySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy import (
    SequenzyResumeConfig,
    sequenzy_source,
    validate_credentials as validate_sequenzy_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SequenzySource(ResumableSource[SequenzySourceConfig, SequenzyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    api_docs_url = "https://docs.sequenzy.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEQUENZY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Sequenzy API key is invalid or was revoked. Create a new key in Sequenzy under Settings > API Keys and update the source.",
            "403 Client Error: Forbidden for url": "Your Sequenzy API key does not have access to this data. Check the key's permissions and the company ID, then try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SequenzySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SequenzySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sequenzy_credentials(config.api_key, config.company_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SequenzyResumeConfig]:
        return ResumableSourceManager[SequenzyResumeConfig](inputs, SequenzyResumeConfig)

    def source_for_pipeline(
        self,
        config: SequenzySourceConfig,
        resumable_source_manager: ResumableSourceManager[SequenzyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sequenzy_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            company_id=config.company_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEQUENZY,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Sequenzy",
            caption=(
                "Create an API key in Sequenzy under **Workspace Settings > API Keys** with read "
                "access to subscribers, tags, lists, segments, campaigns, sequences, and analytics."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/sequenzy",
            iconPath="/static/services/sequenzy.png",
            keywords=["email marketing", "newsletter"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="seq_live_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="company_id",
                        label="Company ID",
                        caption=(
                            "Only needed with an account API key (starts with `seq_user_`): the ID of "
                            "the Sequenzy workspace to sync. Workspace keys (`seq_live_`) already "
                            "belong to one workspace."
                        ),
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
