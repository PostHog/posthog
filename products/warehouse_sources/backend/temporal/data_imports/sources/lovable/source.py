from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lovable import (
    LovableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.lovable import (
    LovableResumeConfig,
    check_endpoint_permissions,
    lovable_source,
    validate_credentials as validate_lovable_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOVABLE_API_VERSION_V1,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LovableSource(ResumableSource[LovableSourceConfig, LovableResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    supported_versions = (LOVABLE_API_VERSION_V1,)
    default_version = LOVABLE_API_VERSION_V1
    api_docs_url = "https://api.lovable.dev/v1/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOVABLE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Lovable API key is invalid or has been revoked. Create a new key in Lovable and reconnect.",
            "402 Client Error": "This table needs a higher Lovable plan. Turn it off in the sync settings, or upgrade the workspace in Lovable.",
            "403 Client Error": "Your Lovable API key does not have permission to read this data. Use a key from an account with access, or turn this table off in the sync settings.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LovableSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: LovableSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_lovable_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_endpoint_permissions(
        self, config: LovableSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return check_endpoint_permissions(config.api_key, self.resolve_api_version(api_version), endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LovableResumeConfig]:
        return ResumableSourceManager[LovableResumeConfig](inputs, LovableResumeConfig)

    def source_for_pipeline(
        self,
        config: LovableSourceConfig,
        resumable_source_manager: ResumableSourceManager[LovableResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lovable_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LOVABLE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Lovable",
            caption=(
                "Connect your Lovable account with an API key to sync workspaces, projects, "
                "members, credit history, and security findings. Member, collaborator, credit, and "
                "PII tables need Lovable's Enterprise plan, and security scans need Business or higher."
            ),
            keywords=["app builder"],
            docsUrl="https://posthog.com/docs/cdp/sources/lovable",
            iconPath="/static/services/lovable.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="lov_...",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
