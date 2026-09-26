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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quo import QuoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.quo import (
    QuoResumeConfig,
    quo_source,
    validate_credentials as validate_quo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QuoSource(ResumableSource[QuoSourceConfig, QuoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://www.quo.com/docs/mdx/api-reference/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.quo.com": "Quo authentication failed. Check that your API key is correct and still active, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.quo.com": "Quo denied access. Check that the API key was created by a workspace owner or admin.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.quo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: QuoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: QuoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_quo_credentials(config.api_key):
            return True, None

        return False, "Invalid Quo API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QuoResumeConfig]:
        return ResumableSourceManager[QuoResumeConfig](inputs, QuoResumeConfig)

    def source_for_pipeline(
        self,
        config: QuoSourceConfig,
        resumable_source_manager: ResumableSourceManager[QuoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return quo_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.QUO,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Quo",
            caption="""Enter your Quo API key to pull your Quo (formerly OpenPhone) data into the PostHog Data warehouse.

You can generate an API key in your Quo workspace settings, under the API tab. You need workspace owner or admin access to do this.""",
            keywords=["openphone", "phone", "sms", "calls"],
            iconPath="/static/services/quo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/quo",
            releaseStatus=ReleaseStatus.ALPHA,
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
