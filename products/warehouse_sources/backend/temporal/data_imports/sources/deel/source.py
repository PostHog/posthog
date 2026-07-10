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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel import (
    DeelResumeConfig,
    deel_source,
    validate_credentials as validate_deel_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeelSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DeelSource(ResumableSource[DeelSourceConfig, DeelResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.deel.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEEL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.letsdeel.com": "Deel authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://api.letsdeel.com": "Deel denied access. Please check that your API token has the read scope for this dataset.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEEL,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Deel",
            caption="""Enter your Deel API token to pull your Deel workforce and payroll data into the PostHog Data warehouse.

Create an organization token in [Deel](https://app.deel.com/developer-center) under More > Developer with read scopes for the data you want to sync (e.g. `people:read`, `contracts:read`, `accounting:read`). Prefer an organization token over a personal token — personal tokens stop working when the user leaves the organization.""",
            iconPath="/static/services/deel.png",
            docsUrl="https://posthog.com/docs/cdp/sources/deel",
            releaseStatus=ReleaseStatus.ALPHA,
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.deel.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DeelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Core Deel objects have no updated-since filter, so every stream is an
        # honest full refresh.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: DeelSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_deel_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DeelResumeConfig]:
        return ResumableSourceManager[DeelResumeConfig](inputs, DeelResumeConfig)

    def source_for_pipeline(
        self,
        config: DeelSourceConfig,
        resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return deel_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
