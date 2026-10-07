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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.turso import TursoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.turso.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.turso.turso import (
    INVALID_TOKEN_MESSAGE,
    PERMISSION_MESSAGE,
    TursoResumeConfig,
    turso_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TursoSource(ResumableSource[TursoSourceConfig, TursoResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.turso.tech/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TURSO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TURSO,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Turso",
            iconPath="/static/services/turso.png",
            docsUrl="https://posthog.com/docs/cdp/sources/turso",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["sqlite", "database", "libsql", "edge"],
            caption=(
                "Import Turso Platform API metadata and usage. Tables stored inside your SQLite databases are not imported. "
                "Use an organization-scoped Platform API token with access to the selected resources, "
                "created with `turso auth api-tokens mint`. Database auth tokens cannot access the Platform API. "
                "Audit logs require the Scaler plan or higher and are disabled by default. "
                "Database usage refreshes the current calendar month."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example-org",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Platform API token",
                        placeholder="",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    ),
                ],
            ),
        )

    def validate_credentials(
        self,
        config: TursoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name)

    def get_schemas(
        self,
        config: TursoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                description=endpoint.description,
                should_sync_default=endpoint.should_sync_default,
                detected_primary_keys=endpoint.primary_keys,
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_TOKEN_MESSAGE,
            "403 Client Error": PERMISSION_MESSAGE,
        }

    def get_endpoint_permissions(
        self,
        config: TursoSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return {name: validate_credentials(config, team_id, name)[1] for name in endpoints}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.turso.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TursoResumeConfig]:
        return ResumableSourceManager(inputs, TursoResumeConfig)

    def source_for_pipeline(
        self,
        config: TursoSourceConfig,
        resumable_source_manager: ResumableSourceManager[TursoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return turso_source(config, inputs, resumable_source_manager)
