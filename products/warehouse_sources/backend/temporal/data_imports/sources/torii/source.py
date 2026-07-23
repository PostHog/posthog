from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.torii import ToriiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.torii import (
    ToriiResumeConfig,
    torii_source,
    validate_credentials as validate_torii_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ToriiSource(ResumableSource[ToriiSourceConfig, ToriiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("1.1",)
    default_version = "1.1"
    api_docs_url = "https://developers.toriihq.com"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TORII

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.toriihq.com": "Your Torii API key is invalid or expired. Please generate a new key from Settings > API Access and reconnect.",
            "403 Client Error: Forbidden for url: https://api.toriihq.com": "Your Torii API key does not have permission to access this resource.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.torii.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ToriiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ToriiSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_torii_credentials(config.api_key):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ToriiResumeConfig]:
        return ResumableSourceManager[ToriiResumeConfig](inputs, ToriiResumeConfig)

    def source_for_pipeline(
        self,
        config: ToriiSourceConfig,
        resumable_source_manager: ResumableSourceManager[ToriiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return torii_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TORII,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Torii",
            caption="Import discovered SaaS apps, users, contracts, and spend transactions from Torii.",
            docsUrl="https://posthog.com/docs/cdp/sources/torii",
            iconPath="/static/services/torii.png",
            keywords=["saas management", "spend", "licenses", "contracts"],
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
                        caption="Generate an API key in Torii under **Settings > API Access** (admin permissions required).",
                    ),
                ],
            ),
        )
