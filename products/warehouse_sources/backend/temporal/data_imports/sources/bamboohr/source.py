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
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr import (
    BambooHRResumeConfig,
    bamboohr_source,
    validate_credentials as validate_bamboohr_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BambooHRSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BambooHRSource(ResumableSource[BambooHRSourceConfig, BambooHRResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://documentation.bamboohr.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BAMBOOHR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BAMBOO_HR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="BambooHR",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your BambooHR company subdomain and API key to pull your HR data into the PostHog Data warehouse.

You can generate an API key from your BambooHR account under **Account Settings → API Keys** (requires admin permissions).

Make sure your API key has access to the data you want to sync (employee, time off, and account metadata).""",
            iconPath="/static/services/bamboohr.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bamboohr",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Company subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BambooHRSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BambooHRSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_bamboohr_credentials(config.subdomain, config.api_key, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your BambooHR API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url": "Your BambooHR API key does not have the required permissions. Please check the key permissions and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BambooHRResumeConfig]:
        return ResumableSourceManager[BambooHRResumeConfig](inputs, BambooHRResumeConfig)

    def source_for_pipeline(
        self,
        config: BambooHRSourceConfig,
        resumable_source_manager: ResumableSourceManager[BambooHRResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bamboohr_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
