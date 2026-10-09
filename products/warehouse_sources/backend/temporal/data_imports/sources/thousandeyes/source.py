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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thousandeyes import (
    ThousandeyesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.thousandeyes import (
    AUTH_ERRORS,
    ThousandeyesResumeConfig,
    thousandeyes_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ThousandeyesSource(ResumableSource[ThousandeyesSourceConfig, ThousandeyesResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v7",)
    default_version = "v7"
    api_docs_url = "https://developer.cisco.com/docs/thousandeyes/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THOUSANDEYES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.THOUSANDEYES,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cisco ThousandEyes",
            iconPath="/static/services/thousandeyes.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Create an API token in Manage > Account Settings > Users and Roles > Profile > User API Tokens. "
            "Alerts and initial HTTP results cover the last 30 days. Sync at least every 30 days to avoid gaps.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_group_id",
                        label="Account group ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to use your default account group",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(AUTH_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ThousandeyesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"http_server_results"})

    def validate_credentials(
        self,
        config: ThousandeyesSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ThousandeyesResumeConfig]:
        return ResumableSourceManager(inputs, ThousandeyesResumeConfig)

    def source_for_pipeline(
        self,
        config: ThousandeyesSourceConfig,
        resumable_source_manager: ResumableSourceManager[ThousandeyesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return thousandeyes_source(
            config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )
