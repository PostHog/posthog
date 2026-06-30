from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WorkOSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import (
    WorkOSResumeConfig,
    validate_credentials as validate_workos_credentials,
    workos_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkOSSource(ResumableSource[WorkOSSourceConfig, WorkOSResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKOS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORK_OS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="WorkOS",
            releaseStatus="alpha",
            caption="""Enter your WorkOS API key to sync your WorkOS data into the PostHog Data warehouse.

You can find your API key in the [WorkOS Dashboard](https://dashboard.workos.com/) under **API Keys**.

The key starts with `sk_`.
""",
            iconPath="/static/services/workos.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.workos.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WorkOSSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # WorkOS list endpoints expose no server-side timestamp filter, so only
        # full refresh is supported.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.workos.com": "Your WorkOS API key is invalid or has been revoked. Please update the key in your WorkOS dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.workos.com": "Your WorkOS API key does not have permission to access this endpoint. Please check the key's scopes in your WorkOS dashboard.",
            # WorkOS returns 422 for a syntactically valid list request it can't fulfil for this
            # account — e.g. the Directory Sync endpoints (directory_users/directory_groups) when
            # Directory Sync isn't provisioned. It's deterministic, so retrying never resolves it.
            "422 Client Error: Unprocessable Entity for url: https://api.workos.com": "WorkOS could not process the request for one of the endpoints being synced. This usually means the data isn't available for your WorkOS account (for example, Directory Sync isn't configured). Please check your WorkOS configuration and the endpoints you're syncing, then reconnect.",
        }

    def validate_credentials(
        self, config: WorkOSSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_workos_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WorkOSResumeConfig]:
        return ResumableSourceManager[WorkOSResumeConfig](inputs, WorkOSResumeConfig)

    def source_for_pipeline(
        self,
        config: WorkOSSourceConfig,
        resumable_source_manager: ResumableSourceManager[WorkOSResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return workos_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
