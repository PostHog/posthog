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
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ynab import YnabSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.ynab import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    YnabResumeConfig,
    validate_credentials,
    ynab_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YnabSource(ResumableSource[YnabSourceConfig, YnabResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://api.ynab.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YNAB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YNAB,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="YNAB (You Need A Budget)",
            caption="Import data from all accessible YNAB plans using a personal access token from "
            "[Developer Settings](https://app.ynab.com/settings/developer). "
            "Tables use full refresh to include edits to older records.",
            docsUrl="https://posthog.com/docs/cdp/sources/ynab",
            iconPath="/static/services/ynab.png",
            keywords=["budgeting", "personal finance", "you need a budget"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_schemas(
        self,
        config: YnabSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: YnabSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None:
            schema_for_resource(ENDPOINTS, schema_name)
        return validate_credentials(config.api_key, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[YnabResumeConfig]:
        return ResumableSourceManager(inputs, YnabResumeConfig, namespace=inputs.schema_name)

    def source_for_pipeline(
        self,
        config: YnabSourceConfig,
        resumable_source_manager: ResumableSourceManager[YnabResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ynab_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.ynab.com/": AUTH_ERROR,
            "403 Client Error: Forbidden for url: https://api.ynab.com/": PERMISSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS
