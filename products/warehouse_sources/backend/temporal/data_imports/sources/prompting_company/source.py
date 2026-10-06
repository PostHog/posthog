from datetime import UTC, date, datetime
from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptingcompany import (
    PromptingCompanySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.prompting_company import (
    PromptingCompanyResumeConfig,
    prompting_company_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PromptingCompanySource(ResumableSource[PromptingCompanySourceConfig, PromptingCompanyResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.promptingcompany.com/api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROMPTINGCOMPANY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PromptingCompanySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)

    def validate_credentials(
        self,
        config: PromptingCompanySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            start_date = date.fromisoformat(config.start_date)
        except ValueError:
            return False, "Enter the analytics start date as YYYY-MM-DD."
        if start_date.isoformat() != config.start_date:
            return False, "Enter the analytics start date as YYYY-MM-DD."
        if start_date > datetime.now(UTC).date():
            return False, "The analytics start date must be today or earlier."
        return validate_credentials(config, schema_name)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[PromptingCompanyResumeConfig]:
        return ResumableSourceManager(inputs, PromptingCompanyResumeConfig)

    def source_for_pipeline(
        self,
        config: PromptingCompanySourceConfig,
        resumable_source_manager: ResumableSourceManager[PromptingCompanyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return prompting_company_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PROMPTINGCOMPANY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="The Prompting Company",
            iconPath="/static/services/prompting_company.png",
            keywords=["geo", "ai visibility", "llm", "share of voice"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create an API key in your organization's Settings > API keys. "
                "Grant `content:read`, `prompts:read`, `simulations:read`, and `analytics:read` for the tables you select. "
                "Content, suggestions, and share of voice use the product ID. Simulation runs cover the whole organization."
            ),
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
                    SourceFieldInputConfig(
                        name="product_id",
                        label="Product ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="product_123",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Analytics start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )
