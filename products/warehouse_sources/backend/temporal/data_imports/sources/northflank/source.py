from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.northflank import (
    NorthflankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank import (
    NorthflankResumeConfig,
    northflank_source,
    validate_credentials as validate_northflank_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NorthflankSource(ResumableSource[NorthflankSourceConfig, NorthflankResumeConfig]):
    codebase_detection = detect(env=("^NORTHFLANK_",), npm=("@northflank/js-client", "@northflank/cli"))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://northflank.com/docs/v1/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NORTHFLANK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.northflank.com": "Your Northflank API token is invalid or has been revoked. Create a new token in your Northflank account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.northflank.com": "Your Northflank API token is missing the permissions needed to sync this data. Grant the required read access, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: NorthflankSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only endpoints with a server-side timestamp filter advertise incremental fields; the rest
        # are full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                # `startTime` is inclusive, so append would duplicate the boundary hour each sync.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: NorthflankSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_northflank_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NorthflankResumeConfig]:
        return ResumableSourceManager[NorthflankResumeConfig](inputs, NorthflankResumeConfig)

    def source_for_pipeline(
        self,
        config: NorthflankSourceConfig,
        resumable_source_manager: ResumableSourceManager[NorthflankResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        incremental_start: Optional[int] = None
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            incremental_start = int(inputs.db_incremental_field_last_value)

        return northflank_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            incremental_start=incremental_start,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NORTHFLANK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Northflank",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Northflank API token to pull your Northflank projects, services, jobs, addons, volumes, pipelines, builds, job runs, workflow runs, release flow runs, plans, and billing usage into the PostHog Data warehouse.

You can create a personal or team API token in your [Northflank account settings](https://app.northflank.com/). Grant it read access to the resources you want to sync. The usage table also needs billing read access.""",
            iconPath="/static/services/northflank.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/northflank",
            keywords=["deployment", "containers", "paas", "devops"],
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
