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
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene import (
    CodesceneResumeConfig,
    codescene_source,
    validate_credentials as validate_codescene_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codescene import (
    CodesceneSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodesceneSource(ResumableSource[CodesceneSourceConfig, CodesceneResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODESCENE

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API token is sent; retargeting it must re-require the token.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODESCENE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CodeScene",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync projects, per-file Code Health metrics, and architectural components from CodeScene.

Create a Personal Access Token from the CodeScene API tokens page with an Admin, Architect, or RestApi role. Leave the API base URL blank to use CodeScene Cloud, or enter your on-prem CodeScene server's API URL (for example `https://codescene.yourcompany.com:3003/api/v2`).""",
            iconPath="/static/services/codescene.png",
            docsUrl="https://posthog.com/docs/cdp/sources/codescene",
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
                        name="base_url",
                        label="API base URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.codescene.io/v2",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your CodeScene API token is invalid or has expired. Generate a new token from the CodeScene API tokens page, then reconnect.",
            "403 Client Error": "Your CodeScene API token does not have the Admin, Architect, or RestApi role required by the API. Update the token's role, then reconnect.",
        }

    def get_schemas(
        self,
        config: CodesceneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CodesceneSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_codescene_credentials(config.api_token, config.base_url, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CodesceneResumeConfig]:
        return ResumableSourceManager[CodesceneResumeConfig](inputs, CodesceneResumeConfig)

    def source_for_pipeline(
        self,
        config: CodesceneSourceConfig,
        resumable_source_manager: ResumableSourceManager[CodesceneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return codescene_source(
            api_token=config.api_token,
            base_url=config.base_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
