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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qdrant import QdrantSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.qdrant import (
    QdrantResumeConfig,
    qdrant_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.settings import (
    API_VERSION,
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QdrantSource(ResumableSource[QdrantSourceConfig, QdrantResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://qdrant.tech/documentation/cloud-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QDRANT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: QdrantSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: QdrantSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QdrantResumeConfig]:
        return ResumableSourceManager(inputs, QdrantResumeConfig)

    def source_for_pipeline(
        self,
        config: QdrantSourceConfig,
        resumable_source_manager: ResumableSourceManager[QdrantResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return qdrant_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.QDRANT,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Qdrant",
            iconPath="/static/services/qdrant.png",
            keywords=["vector", "database", "qdrant", "cloud"],
            caption=(
                "Import Qdrant Cloud infrastructure metadata. "
                "Create a Cloud Management Key in the Cloud Console under Access Management > Cloud Management Keys. "
                "Grant `read:clusters`, `read:backups`, and `read:backup_schedules` for the tables you select. "
                "Copy your account ID from the Cloud Console. Vector data and collections are not included."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Cloud Management Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        required=True,
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
