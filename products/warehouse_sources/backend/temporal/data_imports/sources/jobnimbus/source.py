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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JobNimbusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.jobnimbus import (
    JobNimbusResumeConfig,
    jobnimbus_source,
    validate_credentials as _validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.settings import (
    ENDPOINTS,
    JOBNIMBUS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JobNimbusSource(ResumableSource[JobNimbusSourceConfig, JobNimbusResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://documenter.getpostman.com/view/3919598/S11PpG7g"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JOBNIMBUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JOB_NIMBUS,
            category=DataWarehouseSourceCategory.CRM,
            label="JobNimbus",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your JobNimbus API key to pull your CRM data into the PostHog Data warehouse.

You can create an API key under **Settings → API** in [JobNimbus](https://app.jobnimbus.com). The key grants access to your contacts, jobs, tasks, and activities.
""",
            iconPath="/static/services/jobnimbus.png",
            docsUrl="https://posthog.com/docs/cdp/sources/jobnimbus",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.jobnimbus.com": "Your JobNimbus API key is invalid or has been revoked. Generate a new key under Settings → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.jobnimbus.com": "Your JobNimbus API key does not have access to this data. Check the key's access profile, then reconnect.",
        }

    def get_schemas(
        self,
        config: JobNimbusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — JobNimbus's list endpoints expose no reliably
        # documented server-side timestamp filter, so there is no incremental cursor to advance.
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
        self, config: JobNimbusSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return _validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JobNimbusResumeConfig]:
        return ResumableSourceManager[JobNimbusResumeConfig](inputs, JobNimbusResumeConfig)

    def source_for_pipeline(
        self,
        config: JobNimbusSourceConfig,
        resumable_source_manager: ResumableSourceManager[JobNimbusResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in JOBNIMBUS_ENDPOINTS:
            raise ValueError(f"Unknown JobNimbus schema '{inputs.schema_name}'")

        return jobnimbus_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
