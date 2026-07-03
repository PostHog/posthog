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
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial import (
    FactorialResumeConfig,
    factorial_source,
    validate_credentials as validate_factorial_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.settings import (
    ENDPOINTS,
    FACTORIAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FactorialSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FactorialSource(ResumableSource[FactorialSourceConfig, FactorialResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FACTORIAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FACTORIAL,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Factorial",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Factorial API key to sync your HR, time-off, attendance, payroll, and recruiting data into the PostHog Data warehouse.

Create an API key in your Factorial account under **Settings > API keys** (or **Integrations > Public API**). The key grants read access to your company's data across every table listed below.""",
            iconPath="/static/services/factorial.png",
            docsUrl="https://posthog.com/docs/cdp/sources/factorial",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Factorial API key surfaces as an HTTPError when the RESTClient
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync with an actionable message.
            "401 Client Error": "Invalid or revoked Factorial API key. Create a new key in your Factorial account settings and reconnect.",
            "403 Client Error": "Your Factorial API key does not have access to this data. Check the key's permissions and reconnect.",
            "Unauthorized for url": "Invalid or revoked Factorial API key. Create a new key in your Factorial account settings and reconnect.",
        }

    def get_schemas(
        self,
        config: FactorialSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # No endpoint advertises a curl-verified server-side timestamp filter yet, so every
                # schema is full refresh only (INCREMENTAL_FIELDS is empty — see settings.py).
                supports_incremental=(fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=fields is not None,
                incremental_fields=fields or [],
                should_sync_default=FACTORIAL_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FactorialSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_factorial_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FactorialResumeConfig]:
        return ResumableSourceManager[FactorialResumeConfig](inputs, FactorialResumeConfig)

    def source_for_pipeline(
        self,
        config: FactorialSourceConfig,
        resumable_source_manager: ResumableSourceManager[FactorialResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return factorial_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
