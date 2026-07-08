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
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.ashby import (
    AUTH_ERROR_HINT,
    DEFAULT_PROBE_PATH,
    AshbyResumeConfig,
    ashby_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import ASHBY_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AshbySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AshbySource(ResumableSource[AshbySourceConfig, AshbyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASHBY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ASHBY,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Ashby",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Ashby API key to pull your Ashby (ATS) data into the PostHog Data warehouse.

You can create an API key under **Admin → API Keys** in Ashby. Grant read permissions for the data you want to sync, for example:
- `candidatesRead`, `applicationsRead`, `jobsRead`, `offersRead`, `interviewsRead`, `usersRead`
""",
            iconPath="/static/services/ashby.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ashby",
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
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AshbySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Ashby exposes incremental sync only via an opaque syncToken and an unordered
        # `createdAfter` filter — neither maps safely onto PostHog's timestamp-watermark
        # model — so every endpoint is full refresh for now.
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
        self, config: AshbySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ASHBY_ENDPOINTS:
            return False, f"Unknown Ashby schema '{schema_name}'"

        path = ASHBY_ENDPOINTS[schema_name].path if schema_name is not None else DEFAULT_PROBE_PATH
        status, message = check_access(config.api_key, path)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Ashby API key"
        if status == 403:
            # Valid key without scope for this endpoint. Accept at source-create (the user may
            # only intend to sync a subset); reject when validating a specific schema.
            if schema_name is not None:
                return False, f"Your Ashby API key does not have permission to read '{schema_name}'"
            return True, None

        return False, message or "Could not validate Ashby credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Ashby API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Ashby API key does not have the required permissions. Please check the key's scopes and try again.",
            AUTH_ERROR_HINT: "Your Ashby API key is invalid or lacks the required permissions. Please check the key and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AshbyResumeConfig]:
        return ResumableSourceManager[AshbyResumeConfig](inputs, AshbyResumeConfig)

    def source_for_pipeline(
        self,
        config: AshbySourceConfig,
        resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ashby_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
