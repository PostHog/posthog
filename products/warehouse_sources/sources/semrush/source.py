from typing import cast

from products.warehouse_sources.sources.sdk import (
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
    detect,
)
from products.warehouse_sources.sources.semrush._config import SemrushSourceConfig
from products.warehouse_sources.sources.semrush.canonical_descriptions import CANONICAL_DESCRIPTIONS
from products.warehouse_sources.sources.semrush.semrush import semrush_source, validate_credentials
from products.warehouse_sources.sources.semrush.settings import (
    ACCESS_ERROR,
    API_DOCS_URL,
    API_VERSION,
    AUTH_ERROR,
    DATABASE_ACCESS_ERROR,
    DOMAIN_ERROR,
    DOMAIN_REPORT_ERROR,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    PROJECT_ID_ERROR,
    REQUEST_ERROR,
    TABLES,
)


@SourceRegistry.register
class SemrushSource(SimpleSource[SemrushSourceConfig]):
    codebase_detection = detect(env=("^SEMRUSH_",))

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
            DATABASE_ACCESS_ERROR: DATABASE_ACCESS_ERROR,
            DOMAIN_REPORT_ERROR: DOMAIN_REPORT_ERROR,
            DOMAIN_ERROR: DOMAIN_ERROR,
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
        return build_endpoint_schemas(TABLES, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SemrushSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, config.project_id, team_id)

    def source_for_pipeline(self, config: SemrushSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return semrush_source(
            config.api_key,
            config.project_id,
            inputs.schema_name,
            inputs.team_id,
            inputs.job_id,
            domain=config.domain,
            database=config.database,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

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
                "Connection validation also uses 100 units. "
                "Site audit history costs 10,000 units per audit snapshot, and incremental syncs fetch only new snapshots. "
                "Domain organic reports cost 10 units (keywords) or 40 units (competitors) per row, "
                "and each sync reads up to 10,000 rows."
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
                    SourceFieldInputConfig(
                        name="domain",
                        label="Domain for organic reports",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="example.com",
                        caption="Leave empty to use your Semrush project's domain.",
                        secret=False,
                        sync_setting=True,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Regional database for organic reports",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="us",
                        caption="A Semrush regional database code, such as `us`, `uk` or `de`. Defaults to `us`.",
                        secret=False,
                        sync_setting=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )
