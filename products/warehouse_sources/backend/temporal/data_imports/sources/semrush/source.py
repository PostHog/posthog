from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semrush import (
    SemrushSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.semrush import (
    semrush_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.settings import (
    ACCESS_ERROR,
    API_DOCS_URL,
    API_VERSION,
    AUTH_ERROR,
    ENDPOINTS,
    ERROR_MESSAGES,
    PROJECT_ID_ERROR,
    REQUEST_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SemrushSource(SimpleSource[SemrushSourceConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEMRUSH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **{message: message for message in ERROR_MESSAGES.values()},
            PROJECT_ID_ERROR: PROJECT_ID_ERROR,
            REQUEST_ERROR: REQUEST_ERROR,
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": ACCESS_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SemrushSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: SemrushSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, config.project_id, team_id)

    def source_for_pipeline(self, config: SemrushSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return semrush_source(config.api_key, config.project_id, inputs.schema_name, inputs.team_id, inputs.job_id)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEMRUSH,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Semrush",
            caption=(
                "Requires an SEO Business subscription and a project with Site Audit enabled. "
                "Find your v3 API key under [API keys](https://www.semrush.com/accounts/api-keys/active) in your Semrush profile. "
                "Syncs use your account's API units: 100 units per table request. Retries can use more units. "
                "Connection validation also uses 100 units."
            ),
            iconPath="/static/services/semrush.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key (v3)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
