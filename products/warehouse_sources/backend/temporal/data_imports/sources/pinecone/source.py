from typing import TYPE_CHECKING, cast

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pinecone import (
    PineconeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinecone.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinecone.pinecone import (
    PineconeResumeConfig,
    pinecone_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinecone.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
        CanonicalDescriptions,
    )


@SourceRegistry.register
class PineconeSource(ResumableSource[PineconeSourceConfig, PineconeResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("2026-07",)
    default_version = "2026-07"
    api_docs_url = "https://docs.pinecone.io/reference/api/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINECONE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PINECONE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Pinecone",
            caption="Import index, collection, backup, and restore job metadata from one Pinecone project. "
            "Use a project API key with permission to read the resources you select.",
            docsUrl="https://posthog.com/docs/cdp/sources/pinecone",
            iconPath="/static/services/pinecone.png",
            keywords=["vector", "database", "rag", "embeddings"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Pinecone API key is invalid or expired. Create a new key and reconnect.",
            "403 Client Error": "Your Pinecone API key cannot read this resource. Check the key permissions and project plan.",
        }

    def get_canonical_descriptions(self) -> "CanonicalDescriptions":
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PineconeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PineconeSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "Unknown Pinecone table. Select a table from the source schema list."
        try:
            validate_credentials(config.api_key, self.resolve_api_version(api_version), schema_name or "indexes")
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, self.get_non_retryable_errors()["401 Client Error"]
            if status == 403:
                if schema_name is None:
                    return True, None
                return False, self.get_non_retryable_errors()["403 Client Error"]
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PineconeResumeConfig]:
        return ResumableSourceManager(inputs, PineconeResumeConfig)

    def source_for_pipeline(
        self,
        config: PineconeSourceConfig,
        resumable_source_manager: ResumableSourceManager[PineconeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pinecone_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
