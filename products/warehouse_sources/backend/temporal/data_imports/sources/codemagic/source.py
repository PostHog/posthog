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
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic import (
    CodemagicResumeConfig,
    codemagic_source,
    validate_credentials as validate_codemagic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodemagicSource(ResumableSource[CodemagicSourceConfig, CodemagicResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.codemagic.io/rest-api/codemagic-rest-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODEMAGIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODEMAGIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["ci/cd", "mobile ci/cd"],
            label="Codemagic",
            caption="""Enter a Codemagic personal API token to sync your applications and build history into the PostHog Data warehouse.

You can find your API token under **Account settings > API token** in Codemagic. The actions this token can perform are limited by your own user role within your Codemagic team.

Supported tables:
- `applications`
- `builds`
""",
            iconPath="/static/services/codemagic.png",
            docsUrl="https://posthog.com/docs/cdp/sources/codemagic",
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
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Codemagic API token. Please check the token under Account settings > API token and reconnect.",
            "Unauthorized for url": "Invalid Codemagic API token. Please check the token under Account settings > API token and reconnect.",
        }

    def get_schemas(
        self,
        config: CodemagicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(list(ENDPOINTS), INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CodemagicSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_codemagic_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CodemagicResumeConfig]:
        return ResumableSourceManager[CodemagicResumeConfig](inputs, CodemagicResumeConfig)

    def source_for_pipeline(
        self,
        config: CodemagicSourceConfig,
        resumable_source_manager: ResumableSourceManager[CodemagicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return codemagic_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
